from typing import TypedDict, Optional, Annotated
from app.models.schemas import (
    TerraformPlanResponse,
    SecurityIssue,
    OpaViolation,
    CostEstimate,
    AiReview,
)


def merge_dicts(a: dict, b: dict) -> dict:
    merged = a.copy()
    merged.update(b)
    return merged


class ReviewState(TypedDict):
    pr_number: int
    repository: str
    pr_title: str
    pr_body: str
    changed_files: list[str]

    terraform_init_stdout: str
    terraform_init_stderr: str
    terraform_plan_stdout: str
    terraform_plan_stderr: str
    terraform_plan_exit_code: int
    terraform_plan_response: Optional[TerraformPlanResponse]

    security_issues: Annotated[list[SecurityIssue], merge_dicts]
    opa_violations: Annotated[list[OpaViolation], merge_dicts]
    cost_estimates: Annotated[list[CostEstimate], merge_dicts]
    ai_review: Optional[AiReview]

    opa_input: dict

    review_comment_id: Optional[int]
    status: str
    errors: Annotated[list[str], merge_dicts]


def make_initial_state() -> ReviewState:
    return ReviewState(
        pr_number=0,
        repository="",
        pr_title="",
        pr_body="",
        changed_files=[],
        terraform_init_stdout="",
        terraform_init_stderr="",
        terraform_plan_stdout="",
        terraform_plan_stderr="",
        terraform_plan_exit_code=-1,
        terraform_plan_response=None,
        security_issues=[],
        opa_violations=[],
        cost_estimates=[],
        ai_review=None,
        opa_input={"resources": []},
        review_comment_id=None,
        status="pending",
        errors=[],
    )
