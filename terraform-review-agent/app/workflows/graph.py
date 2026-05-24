from typing import Any, Literal

from langgraph.graph import StateGraph, START, END

from app.models.state import ReviewState
from app.models.schemas import AiReview
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
        work_dir = state.get("terraform_dir") or None
        tool = TerraformTool(work_dir=work_dir) if work_dir else _get_terraform_tool()
        response = await tool.run_full_plan()

        plan_json = ""
        if response.exit_code in (0, 2):
            plan_json = await tool.plan_json()
            if plan_json:
                logger.info("terraform_plan_json_captured", bytes=len(plan_json))

        return {
            "terraform_init_stdout": response.init_stdout,
            "terraform_init_stderr": response.init_stderr,
            "terraform_plan_stdout": response.plan_stdout,
            "terraform_plan_stderr": response.plan_stderr,
            "terraform_plan_exit_code": response.exit_code,
            "terraform_plan_response": response,
            "terraform_plan_json": plan_json,
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
    plan_json = state.get("terraform_plan_json", "") or ""
    plan_stdout = state.get("terraform_plan_stdout", "") or ""

    if plan_json:
        opa_input_resources = _extract_opa_resources_from_json(plan_json)
        logger.info("opa_input_from_json", resources=len(opa_input_resources))
    else:
        opa_input_resources = _extract_opa_resources(plan_stdout)
        logger.info("opa_input_from_stdout", resources=len(opa_input_resources))

    return {
        "opa_input": {
            "resources": opa_input_resources,
            "plan_exit_code": state.get("terraform_plan_exit_code", -1),
        }
    }


def _extract_opa_resources_from_json(plan_json: str) -> list[dict]:
    """Parse terraform show -json output into OPA input resources."""
    import json as _json

    try:
        data = _json.loads(plan_json)
    except Exception:
        return []

    resources: list[dict] = []
    for rc in data.get("resource_changes", []):
        change = rc.get("change", {})
        actions = change.get("actions", [])
        if not actions or actions == ["no-op"]:
            continue

        action = actions[0] if len(actions) == 1 else "replace"
        after = change.get("after") or {}
        address = rc.get("address", "unknown")
        res_type = rc.get("type", "unknown")

        resource: dict = {
            "address": address,
            "type": res_type,
            "action": action,
            "labels": after.get("labels", after.get("tags", {})) or {},
            "member": after.get("member", ""),
            "role": after.get("role", ""),
            "machine_type": after.get("machine_type", after.get("instance_type", "")),
            "instance_type": after.get("instance_type", ""),
            "database_version": after.get("database_version", ""),
            "policy_json": after.get("policy", ""),
            "acl": after.get("acl", ""),
            "encrypted": str(after.get("encrypted", "")).lower(),
        }
        resources.append(resource)

    return resources


def _extract_opa_resources(plan_stdout: str) -> list[dict]:
    import re

    resources: list[dict] = []
    # Match both google_ and aws_ resource types
    blocks = re.split(r"\n  # ((google|aws)_\w+)\.(\w+) will be ", plan_stdout)

    if len(blocks) < 4:
        return resources

    # blocks[0] is preamble; groups: full_type, provider, name, body repeat
    i = 1
    while i + 3 < len(blocks):
        res_type = blocks[i].strip()
        # blocks[i+1] = provider match group (google|aws) — skip
        res_name = blocks[i + 2].strip()
        body = blocks[i + 3]
        i += 4

        # Determine where this block ends (next resource or end)
        end_match = re.search(r"\n  # (?:google|aws)_", body)
        if end_match:
            body = body[: end_match.start()]

        address = f"{res_type}.{res_name}"
        resource = {
            "address": address,
            "type": res_type,
            "action": "create",
            "labels": {},
            "member": "",
            "role": "",
            "machine_type": "",
            "database_version": "",
            "policy_json": "",
            # AWS-specific fields
            "instance_type": "",
            "acl": "",
            "encrypted": "",
        }

        if '"allUsers"' in body:
            resource["member"] = "allUsers"
        elif '"allAuthenticatedUsers"' in body:
            resource["member"] = "allAuthenticatedUsers"

        role_match = re.search(r'\+\s+role\s+=\s+"([^"]+)"', body)
        if role_match:
            resource["role"] = role_match.group(1)

        machine_match = re.search(r'\+\s+machine_type\s+=\s+"([^"]+)"', body)
        if machine_match:
            resource["machine_type"] = machine_match.group(1)

        # AWS instance_type
        instance_match = re.search(r'\+\s+instance_type\s+=\s+"([^"]+)"', body)
        if instance_match:
            resource["instance_type"] = instance_match.group(1)
            resource["machine_type"] = instance_match.group(1)

        db_match = re.search(r'\+\s+database_version\s+=\s+"([^"]+)"', body)
        if db_match:
            resource["database_version"] = db_match.group(1)

        # AWS ACL
        acl_match = re.search(r'\+\s+acl\s+=\s+"([^"]+)"', body)
        if acl_match:
            resource["acl"] = acl_match.group(1)
            resource["labels"]["acl"] = acl_match.group(1)

        # AWS encrypted flag
        encrypted_match = re.search(r'\+\s+encrypted\s+=\s+(true|false)', body)
        if encrypted_match:
            resource["encrypted"] = encrypted_match.group(1)
            resource["labels"]["encrypted"] = encrypted_match.group(1)

        # Tags/labels as key=value pairs inside the plan block
        label_matches = re.findall(
            r'\+\s+"([^"]+)"\s+=\s+"([^"]+)"',
            body,
        )
        for k, v in label_matches:
            resource["labels"][k] = v

        resources.append(resource)

    return resources


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


async def github_status_node(state: ReviewState) -> dict[str, Any]:
    logger.info("workflow_node:github_status")
    try:
        commit_sha = state.get("commit_sha", "")
        if not commit_sha:
            logger.info("github_status_skipped_no_sha")
            return {}

        ai_review = state.get("ai_review")
        approved = ai_review.approved if ai_review else False
        score = ai_review.score if ai_review else 0

        tool = _get_github_tool()
        await tool.set_commit_status(commit_sha, approved=approved, score=score)
        return {}
    except Exception as e:
        logger.error("github_status_node_failed", error=str(e))
        return {"errors": [f"GitHub status error: {str(e)}"]}


async def should_run_plan(state: ReviewState) -> Literal["continue", "skip_plan"]:
    changed_files = state.get("changed_files", [])
    has_tf_files = any(f.endswith(".tf") for f in changed_files)
    force_run = state.get("terraform_plan_exit_code", -1) != -1
    direct_api_call = len(changed_files) == 0

    if direct_api_call or has_tf_files or force_run:
        return "continue"
    return "skip_plan"


async def check_plan_result(state: ReviewState) -> Literal["continue", "failed"]:
    exit_code = state.get("terraform_plan_exit_code", -1)
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
    workflow.add_node("github_status_node", github_status_node)

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

    # After ai_review: post PR comment and set commit status in parallel
    workflow.add_edge("ai_review_node", "github_comment_node")
    workflow.add_edge("ai_review_node", "github_status_node")
    workflow.add_edge("github_comment_node", END)
    workflow.add_edge("github_status_node", END)

    return workflow.compile()


graph = create_review_graph()
