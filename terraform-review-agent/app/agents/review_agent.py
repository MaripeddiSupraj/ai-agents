import json
from typing import Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.models.config import get_settings
from app.models.state import ReviewState
from app.models.schemas import AiReview, SecurityIssue, OpaViolation, CostEstimate
from app.prompts.review_prompts import REVIEW_SYSTEM_PROMPT, REVIEW_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AIReviewAgent:
    def __init__(self) -> None:
        settings = get_settings()
        self._llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
            api_key=settings.openai_api_key,
        )
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", REVIEW_SYSTEM_PROMPT),
            ("human", REVIEW_USER_PROMPT),
        ])

    async def __call__(self, state: ReviewState) -> dict[str, Any]:
        logger.info("ai_review_starting")

        plan_output = state.get("terraform_plan_stdout", "") or ""
        security_issues = state.get("security_issues", [])
        opa_violations = state.get("opa_violations", [])
        cost_estimates = state.get("cost_estimates", [])
        pr_title = state.get("pr_title", "") or "No title provided"
        pr_body = state.get("pr_body", "") or "No description provided"

        if not plan_output.strip():
            logger.info("ai_review_skipped_no_plan")
            return {
                "ai_review": AiReview(
                    summary="No Terraform plan output to review.",
                    risks=[],
                    recommendations=[],
                    score=50,
                    approved=False,
                )
            }

        try:
            messages = await self._prompt.ainvoke({
                "plan_output": plan_output[:15000],
                "pr_title": pr_title,
                "pr_body": pr_body[:2000],
                "security_results": self._format_security(security_issues),
                "opa_results": self._format_opa(opa_violations),
                "cost_results": self._format_cost(cost_estimates),
            })
            response = await self._llm.ainvoke(messages)
            review = self._parse_response(response.content)
            logger.info("ai_review_completed", score=review.score, approved=review.approved)
            return {"ai_review": review}
        except Exception as e:
            logger.error("ai_review_failed", error=str(e))
            return {
                "ai_review": AiReview(
                    summary=f"AI review failed: {str(e)}",
                    risks=["Review could not be completed due to an error"],
                    recommendations=["Check logs and retry"],
                    score=0,
                    approved=False,
                )
            }

    def _format_security(self, issues: list[SecurityIssue]) -> str:
        if not issues:
            return "No security issues detected."
        lines = [f"- [{i.severity}] {i.resource}: {i.message}" for i in issues]
        return "\n".join(lines)

    def _format_opa(self, violations: list[OpaViolation]) -> str:
        if not violations:
            return "No OPA policy violations."
        lines = [
            f"- [{v.severity}] Policy: {v.policy}, Resource: {v.resource}: {v.message}"
            for v in violations
        ]
        return "\n".join(lines)

    def _format_cost(self, estimates: list[CostEstimate]) -> str:
        if not estimates:
            return "No cost estimates available."
        lines = [f"- {e.resource} ({e.resource_type}): ${e.estimated_monthly_cost:.2f}/mo" for e in estimates]
        total = sum(e.estimated_monthly_cost for e in estimates)
        lines.append(f"\nTotal: ${total:.2f}/mo")
        return "\n".join(lines)

    def _parse_response(self, content: str) -> AiReview:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]

        try:
            data = json.loads(cleaned)
            return AiReview(
                summary=data.get("summary", "No summary provided."),
                risks=data.get("risks", []),
                recommendations=data.get("recommendations", []),
                score=data.get("score", 50),
                approved=data.get("approved", False),
            )
        except json.JSONDecodeError:
            logger.warning("ai_review_parse_failed", raw=content[:200])
            return AiReview(
                summary="Could not parse AI review response.",
                risks=["Parse error in review generation"],
                recommendations=["Review raw logs for details"],
                score=0,
                approved=False,
            )
