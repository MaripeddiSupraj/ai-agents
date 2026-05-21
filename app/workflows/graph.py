import json
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END

from app.models.state import ReviewState, make_initial_state
from app.models.schemas import SecurityIssue, OpaViolation, CostEstimate, AiReview
from app.tools.terraform_tools import TerraformTool
from app.tools.opa_tools import OpaTool
from app.tools.github_tools import GitHubTool
from app.agents.security_agent import SecurityScanAgent
from app.agents.cost_agent import CostAnalysisAgent
from app.agents.review_agent import AIReviewAgent
from app.utils.logger import get_logger

logger = get_logger(__name__)


_terraform_tool: TerraformTool | None = None
_opa_tool: OpaTool | None = None
_security_agent: SecurityScanAgent | None = None
_cost_agent: CostAnalysisAgent | None = None
_review_agent: AIReviewAgent | None = None
_github_tool: GitHubTool | None = None


def _get_terraform_tool() -> TerraformTool:
    global _terraform_tool
    if _terraform_tool is None:
        _terraform_tool = TerraformTool()
    return _terraform_tool


def _get_opa_tool() -> OpaTool:
    global _opa_tool
    if _opa_tool is None:
        _opa_tool = OpaTool()
    return _opa_tool


def _get_security_agent() -> SecurityScanAgent:
    global _security_agent
    if _security_agent is None:
        _security_agent = SecurityScanAgent()
    return _security_agent


def _get_cost_agent() -> CostAnalysisAgent:
    global _cost_agent
    if _cost_agent is None:
        _cost_agent = CostAnalysisAgent()
    return _cost_agent


def _get_review_agent() -> AIReviewAgent:
    global _review_agent
    if _review_agent is None:
        _review_agent = AIReviewAgent()
    return _review_agent


def _get_github_tool() -> GitHubTool:
    global _github_tool
    if _github_tool is None:
        _github_tool = GitHubTool()
    return _github_tool


async def terraform_plan_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:terraform_plan")
    try:
        tool = _get_terraform_tool()
        response = await tool.run_full_plan()
        return {
            "terraform_init_stdout": response.init_stdout,
            "terraform_init_stderr": response.init_stderr,
            "terraform_plan_stdout": response.plan_stdout,
            "terraform_plan_stderr": response.plan_stderr,
            "terraform_plan_exit_code": response.exit_code,
            "terraform_plan_response": response,
            "status": "planned" if response.exit_code in (0, 2) else "plan_failed",
            "errors": [f"Terraform plan failed: {response.error}"] if response.error else [],
        }
    except Exception as e:
        logger.error("terraform_plan_node_failed", error=str(e))
        return {
            "status": "plan_failed",
            "errors": [f"Terraform plan error: {str(e)}"],
        }


async def prepare_opa_input(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:prepare_opa_input")
    plan_stdout = state.get("terraform_plan_stdout", "") or ""
    tool = _get_terraform_tool()
    resources = tool.parse_plan_resources(plan_stdout)

    opa_input_resources = []
    for r in resources:
        opa_input_resources.append({
            "address": r["address"],
            "type": r.get("address", "").split(".")[0] if "." in r.get("address", "") else "unknown",
            "action": r["action"],
            "tags": {},
            "public_access_blocked": False,
            "policy_json": "",
            "instance_type": "",
            "engine": "",
        })

    return {
        "opa_input": {
            "resources": opa_input_resources,
            "plan_exit_code": state.get("terraform_plan_exit_code", -1),
        }
    }


async def security_scan_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:security_scan")
    try:
        agent = _get_security_agent()
        return await agent(state)
    except Exception as e:
        logger.error("security_scan_node_failed", error=str(e))
        return {"security_issues": [], "errors": [f"Security scan error: {str(e)}"]}


async def opa_validation_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:opa_validation")
    try:
        tool = _get_opa_tool()
        opa_input_data = state.get("opa_input", {"resources": []})
        violations = await tool.evaluate_all(opa_input_data)
        return {"opa_violations": violations}
    except Exception as e:
        logger.error("opa_validation_node_failed", error=str(e))
        return {"opa_violations": [], "errors": [f"OPA validation error: {str(e)}"]}


async def cost_analysis_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:cost_analysis")
    try:
        agent = _get_cost_agent()
        return await agent(state)
    except Exception as e:
        logger.error("cost_analysis_node_failed", error=str(e))
        return {"cost_estimates": [], "errors": [f"Cost analysis error: {str(e)}"]}


async def ai_review_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:ai_review")
    try:
        agent = _get_review_agent()
        return await agent(state)
    except Exception as e:
        logger.error("ai_review_node_failed", error=str(e))
        return {
            "ai_review": AiReview(
                summary="AI review failed.",
                risks=[f"Error: {str(e)}"],
                recommendations=["Check logs for details"],
                score=0,
                approved=False,
            )
        }


async def github_comment_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:github_comment")
    try:
        tool = _get_github_tool()
        pr_number = state.get("pr_number", 0)
        if not pr_number:
            logger.info("github_comment_skipped_no_pr")
            return {}

        from app.models.schemas import ReviewOutput

        output = ReviewOutput(
            pr_number=pr_number,
            repository=state.get("repository", ""),
            status=state.get("status", "completed"),
            security_issues=state.get("security_issues", []),
            opa_violations=state.get("opa_violations", []),
            cost_estimates=state.get("cost_estimates", []),
            ai_review=state.get("ai_review"),
            errors=state.get("errors", []),
        )

        comment_id = await tool.post_pr_comment(pr_number, output)
        return {"review_comment_id": comment_id, "status": "commented"}
    except Exception as e:
        logger.error("github_comment_node_failed", error=str(e))
        return {"errors": [f"GitHub comment error: {str(e)}"]}


async def should_run_plan(state: ReviewState) -> Literal["continue", "skip_plan"]:
    changed_files = state.get("changed_files", [])
    has_tf_files = any(f.endswith(".tf") for f in changed_files)
    force_run = state.get("terraform_plan_exit_code", -1) != -1

    if has_tf_files or force_run:
        return "continue"
    return "skip_plan"


async def check_plan_result(state: ReviewState) -> Literal["continue", "failed"]:
    exit_code = state.get("terraform_plan_exit_code", -1)
    errors = state.get("errors", [])
    if exit_code == -1:
        return "failed"
    if exit_code not in (0, 2):
        return "failed"
    return "continue"


def create_review_graph() -> StateGraph:
    workflow = StateGraph(ReviewState)

    workflow.add_node("terraform_plan_node", terraform_plan_node)
    workflow.add_node("prepare_opa_input", prepare_opa_input)
    workflow.add_node("security_scan_node", security_scan_node)
    workflow.add_node("opa_validation_node", opa_validation_node)
    workflow.add_node("cost_analysis_node", cost_analysis_node)
    workflow.add_node("ai_review_node", ai_review_node)
    workflow.add_node("github_comment_node", github_comment_node)

    workflow.add_conditional_edges(
        START,
        should_run_plan,
        {
            "continue": "terraform_plan_node",
            "skip_plan": "ai_review_node",
        },
    )

    workflow.add_conditional_edges(
        "terraform_plan_node",
        check_plan_result,
        {
            "continue": "prepare_opa_input",
            "failed": END,
        },
    )

    workflow.add_edge("prepare_opa_input", "security_scan_node")

    workflow.add_edge("security_scan_node", "opa_validation_node")
    workflow.add_edge("security_scan_node", "cost_analysis_node")

    workflow.add_edge("opa_validation_node", "ai_review_node")
    workflow.add_edge("cost_analysis_node", "ai_review_node")

    workflow.add_edge("ai_review_node", "github_comment_node")
    workflow.add_edge("github_comment_node", END)

    return workflow.compile()


graph = create_review_graph()
