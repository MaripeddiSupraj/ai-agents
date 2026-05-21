from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.config import get_settings
from app.models.state import make_initial_state
from app.utils.logger import setup_logging, get_logger
from app.utils.redis_client import RedisClient
from app.models.schemas import ReviewOutput, TerraformPlanRequest


setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_starting", name=settings.app_name, version=settings.app_version)
    redis_client = RedisClient.get_instance()
    await redis_client.connect()
    yield
    await redis_client.disconnect()
    logger.info("app_shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health_check():
    redis_client = RedisClient.get_instance()
    return {
        "status": "healthy",
        "version": settings.app_version,
        "redis_connected": redis_client.is_connected,
    }


@app.post("/review", response_model=ReviewOutput, tags=["review"])
async def run_review(request: TerraformPlanRequest):
    from app.tools.terraform_tools import TerraformTool
    from app.workflows.graph import create_review_graph

    try:
        logger.info("review_requested", directory=request.directory)
        terraform_tool = TerraformTool(work_dir=request.directory)

        initial = make_initial_state()
        initial["pr_number"] = settings.github_pr_number or 0
        initial["repository"] = settings.github_repository
        initial["changed_files"] = []
        initial["pr_title"] = ""
        initial["pr_body"] = ""

        graph = create_review_graph()
        result = await graph.ainvoke(dict(initial))

        plan_response = result.get("terraform_plan_response")

        return ReviewOutput(
            pr_number=result.get("pr_number", 0),
            repository=result.get("repository", ""),
            status=result.get("status", "completed"),
            terraform_plan=plan_response,
            security_issues=result.get("security_issues", []),
            opa_violations=result.get("opa_violations", []),
            cost_estimates=result.get("cost_estimates", []),
            ai_review=result.get("ai_review"),
            errors=result.get("errors", []),
        )
    except Exception as e:
        logger.error("review_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/github", tags=["webhook"])
async def github_webhook(payload: dict):
    import json

    logger.info("github_webhook_received", event=payload.get("action"))

    try:
        pr_number = (
            payload.get("pull_request", {})
            .get("number", 0)
        )
        repo_full_name = (
            payload.get("repository", {})
            .get("full_name", "")
        )
        changed_files = [
            f.get("filename", "")
            for f in payload.get("pull_request", {}).get("files", [])
        ] if "pull_request" in payload else []

        has_tf_files = any(f.endswith(".tf") for f in changed_files)
        if not has_tf_files:
            logger.info("github_webhook_no_tf_files", pr=pr_number)
            return {"status": "skipped", "reason": "No Terraform files changed"}

        from app.models.state import make_initial_state
        from app.workflows.graph import create_review_graph

        initial = make_initial_state()
        initial["pr_number"] = pr_number
        initial["repository"] = repo_full_name
        initial["changed_files"] = changed_files
        initial["pr_title"] = payload.get("pull_request", {}).get("title", "")
        initial["pr_body"] = payload.get("pull_request", {}).get("body", "")

        graph = create_review_graph()
        result = await graph.ainvoke(dict(initial))

        logger.info(
            "github_webhook_review_complete",
            pr=pr_number,
            status=result.get("status"),
            issues=len(result.get("security_issues", [])),
            violations=len(result.get("opa_violations", [])),
        )
        return {
            "status": "completed",
            "pr_number": pr_number,
            "review_status": result.get("status"),
        }
    except Exception as e:
        logger.error("github_webhook_failed", error=str(e))
        return {"status": "error", "detail": str(e)}
