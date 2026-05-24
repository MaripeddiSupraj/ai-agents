import hashlib
import hmac
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
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
    from app.workflows.graph import create_review_graph

    try:
        logger.info("review_requested", directory=request.directory)

        initial = make_initial_state()
        initial["pr_number"] = settings.github_pr_number or 0
        initial["repository"] = settings.github_repository
        initial["changed_files"] = []
        initial["pr_title"] = ""
        initial["pr_body"] = ""
        initial["terraform_dir"] = request.directory
        initial["commit_sha"] = request.commit_sha

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


def _verify_github_signature(body: bytes, signature_header: str, secret: str) -> bool:
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.post("/webhook/github", tags=["webhook"])
async def github_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_github_signature(body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json
    payload = json.loads(body)
    logger.info("github_webhook_received", action=payload.get("action"))

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

        from app.workflows.graph import create_review_graph

        commit_sha = payload.get("pull_request", {}).get("head", {}).get("sha", "")

        initial = make_initial_state()
        initial["pr_number"] = pr_number
        initial["repository"] = repo_full_name
        initial["changed_files"] = changed_files
        initial["pr_title"] = payload.get("pull_request", {}).get("title", "")
        initial["pr_body"] = payload.get("pull_request", {}).get("body", "")
        initial["commit_sha"] = commit_sha

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
