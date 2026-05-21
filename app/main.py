from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.config import get_settings
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
        graph = create_review_graph()
        result = await graph.ainvoke({
            "pr_number": settings.github_pr_number or 0,
            "repository": settings.github_repository,
            "terraform_init_stdout": "",
            "terraform_init_stderr": "",
            "terraform_plan_stdout": "",
            "terraform_plan_stderr": "",
            "terraform_plan_exit_code": -1,
            "terraform_plan_response": None,
            "pr_title": "",
            "pr_body": "",
            "changed_files": [],
            "security_issues": [],
            "opa_violations": [],
            "cost_estimates": [],
            "ai_review": None,
            "review_comment_id": None,
            "status": "pending",
            "errors": [],
        })
        return ReviewOutput(
            pr_number=result.get("pr_number", 0),
            repository=result.get("repository", ""),
            status=result.get("status", "completed"),
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
    logger.info("github_webhook_received", event=payload.get("action"))
    return {"status": "acknowledged"}
