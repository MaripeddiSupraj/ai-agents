import json
import re
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.models.config import get_settings
from app.models.state import ReviewState
from app.models.schemas import CostEstimate
from app.tools.cost_tools import CostTool
from app.prompts.cost_prompts import COST_SYSTEM_PROMPT, COST_USER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


RESOURCE_PATTERN = re.compile(
    r"(aws_\w+)\.\w+"
)


class CostAnalysisAgent:
    def __init__(self) -> None:
        settings = get_settings()
        self._llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
            api_key=settings.openai_api_key,
        )
        self._cost_tool = CostTool()
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", COST_SYSTEM_PROMPT),
            ("human", COST_USER_PROMPT),
        ])

    async def __call__(self, state: ReviewState) -> dict[str, Any]:
        logger.info("cost_analysis_starting")

        plan_output = state.get("terraform_plan_stdout", "") or ""
        if not plan_output.strip():
            logger.info("cost_analysis_skipped_no_plan")
            return {"cost_estimates": []}

        try:
            resource_types = self._extract_resource_types(plan_output)
            if not resource_types:
                return {"cost_estimates": []}

            estimates = await self._cost_tool.estimate_all(resource_types)
            cost_summary = self._summarize_estimates(estimates)

            messages = await self._prompt.ainvoke({
                "plan_output": plan_output[:15000],
                "cost_estimates": cost_summary,
            })
            response = await self._llm.ainvoke(messages)
            logger.info(
                "cost_analysis_completed",
                resources=len(resource_types),
                estimated_total=sum(e.estimated_monthly_cost for e in estimates),
            )
            return {"cost_estimates": estimates}
        except Exception as e:
            logger.error("cost_analysis_failed", error=str(e))
            return {"cost_estimates": []}

    def _extract_resource_types(
        self, plan_output: str
    ) -> list[tuple[str, str]]:
        seen = set()
        resources: list[tuple[str, str]] = []
        for match in RESOURCE_PATTERN.finditer(plan_output):
            resource_type = match.group(1)
            if resource_type not in seen:
                seen.add(resource_type)
                resources.append((resource_type, match.group(0)))
        return resources

    def _summarize_estimates(self, estimates: list[CostEstimate]) -> str:
        if not estimates:
            return "No cost estimates available."
        lines = []
        total = 0.0
        for est in estimates:
            total += est.estimated_monthly_cost
            lines.append(
                f"- {est.resource} ({est.resource_type}): ~${est.estimated_monthly_cost:.2f}/mo"
            )
        lines.append(f"\nTotal estimated monthly cost: ${total:.2f}")
        return "\n".join(lines)
