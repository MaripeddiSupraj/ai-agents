from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime, timezone


class TerraformPlanRequest(BaseModel):
    directory: str = Field(default="./terraform/sample", description="Terraform root module directory")


class TerraformPlanResponse(BaseModel):
    init_stdout: str = ""
    init_stderr: str = ""
    plan_stdout: str = ""
    plan_stderr: str = ""
    exit_code: int = 0
    error: Optional[str] = None


class SecurityIssue(BaseModel):
    severity: str = Field(description="CRITICAL, HIGH, MEDIUM, or LOW")
    category: str = Field(description="e.g. public_s3, wildcard_iam, missing_tags, destructive_change")
    resource: str = Field(description="Terraform resource address")
    message: str = Field(description="Human-readable description")
    recommendation: str = Field(description="How to fix")


class OpaViolation(BaseModel):
    policy: str = Field(description="Rego policy name")
    resource: str = Field(description="Resource address")
    message: str = Field(description="Violation detail")
    severity: str = Field(default="MEDIUM")


class CostEstimate(BaseModel):
    resource: str = Field(description="Terraform resource address")
    resource_type: str = Field(description="AWS resource type")
    estimated_monthly_cost: float = 0.0
    currency: str = "USD"
    details: str = ""


class AiReview(BaseModel):
    summary: str = Field(description="High-level review summary (2-3 sentences)")
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    score: int = Field(default=0, ge=0, le=100, description="Overall quality/risk score")
    approved: bool = False


class ReviewOutput(BaseModel):
    pr_number: int = 0
    repository: str = ""
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "completed"
    terraform_plan: Optional[TerraformPlanResponse] = None
    security_issues: list[SecurityIssue] = Field(default_factory=list)
    opa_violations: list[OpaViolation] = Field(default_factory=list)
    cost_estimates: list[CostEstimate] = Field(default_factory=list)
    ai_review: Optional[AiReview] = None
    review_comment_url: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
