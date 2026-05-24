import json
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.models.config import get_settings
from app.models.state import ReviewState
from app.models.schemas import SecurityIssue
from app.prompts.security_prompts import SECURITY_SYSTEM_PROMPT, SECURITY_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SecurityScanAgent:
    def __init__(self) -> None:
        settings = get_settings()
        self._llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
            api_key=settings.openai_api_key,
        )
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SECURITY_SYSTEM_PROMPT),
            ("human", SECURITY_USER_PROMPT),
        ])

    async def __call__(self, state: ReviewState) -> dict[str, Any]:
        logger.info("security_scan_starting")

        plan_output = state.get("terraform_plan_stdout", "") or ""
        changed_files = state.get("changed_files", [])
        pr_title = state.get("pr_title", "") or "No title provided"
        pr_body = state.get("pr_body", "") or "No description provided"

        if not plan_output.strip():
            logger.info("security_scan_skipped_no_plan")
            return {"security_issues": []}

        try:
            messages = await self._prompt.ainvoke({
                "plan_output": plan_output[:15000],
                "changed_files": "\n".join(changed_files) if changed_files else "N/A",
                "pr_title": pr_title,
                "pr_body": pr_body[:2000],
            })
            response = await self._llm.ainvoke(messages)
            issues = self._parse_response(response.content)
            logger.info("security_scan_completed", count=len(issues))
            return {"security_issues": issues}
        except Exception as e:
            logger.error("security_scan_failed", error=str(e))
            return {"security_issues": []}

    def _parse_response(self, content: str) -> list[SecurityIssue]:
        issues: list[SecurityIssue] = []
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                for item in data:
                    issues.append(self._parse_issue(item))
            elif isinstance(data, dict):
                found = data.get("issues", data.get("security_issues", []))
                if isinstance(found, list):
                    for item in found:
                        issues.append(self._parse_issue(item))
        except json.JSONDecodeError:
            logger.warning("security_parse_failed_raw", raw=content[:200])

        return issues

    def _parse_issue(self, item: dict) -> SecurityIssue:
        return SecurityIssue(
            severity=item.get("severity", "MEDIUM"),
            category=item.get("category", "unknown"),
            resource=item.get("resource", "unknown"),
            message=item.get("message", "No details provided"),
            recommendation=item.get("recommendation", "Review and fix"),
        )
