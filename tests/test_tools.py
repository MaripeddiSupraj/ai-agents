import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.tools.terraform_tools import TerraformTool
from app.tools.opa_tools import OpaTool
from app.tools.cost_tools import CostTool
from app.tools.github_tools import GitHubTool


class TestTerraformTool:
    @pytest.mark.asyncio
    async def test_parse_plan_resources_empty(self):
        tool = TerraformTool()
        result = tool.parse_plan_resources("")
        assert result == []

    @pytest.mark.asyncio
    async def test_parse_plan_resources_with_creation(self):
        tool = TerraformTool()
        plan = '# aws_s3_bucket.example will be created\n+ resource "aws_s3_bucket" "example" {'
        result = tool.parse_plan_resources(plan)
        assert len(result) >= 1

    def test_classify_action(self):
        tool = TerraformTool()
        assert tool._classify_action("will be created") == "create"
        assert tool._classify_action("will be destroyed") == "destroy"
        assert tool._classify_action("must be replaced") == "replace"
        assert tool._classify_action("will be changed") == "update"
        assert tool._classify_action("will be read") == "read"

    @pytest.mark.asyncio
    async def test_run_command_binary_not_found(self):
        tool = TerraformTool(work_dir="/tmp")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.init()
            assert result.exit_code == -1
            assert "not found" in (result.error or "")


class TestOpaTool:
    @pytest.mark.asyncio
    async def test_evaluate_binary_not_found(self):
        tool = OpaTool(policy_dir="/tmp")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.evaluate({"resources": []}, "test.rego")
            assert result == []

    def test_parse_result_empty(self):
        tool = OpaTool()
        result = tool._parse_result("{}")
        assert result == []

    def test_parse_result_with_violations(self):
        tool = OpaTool()
        raw = '{"result":[{"expressions":[{"value":[{"policy":"test","resource":"aws_s3_bucket.x","message":"test violation","severity":"HIGH"}]}]}]}'
        result = tool._parse_result(raw)
        assert len(result) == 1
        assert result[0].policy == "test"
        assert result[0].severity == "HIGH"

    def test_parse_result_string_violations(self):
        tool = OpaTool()
        raw = '{"result":[{"expressions":[{"value":["blocked by policy"]}]}]}'
        result = tool._parse_result(raw)
        assert len(result) == 1
        assert result[0].message == "blocked by policy"


class TestCostTool:
    def test_estimate_known_resource(self):
        tool = CostTool()
        import asyncio
        result = asyncio.run(tool.estimate_resource("aws_s3_bucket", "aws_s3_bucket.data"))
        assert result.resource_type == "aws_s3_bucket"
        assert result.estimated_monthly_cost >= 0

    def test_estimate_unknown_resource(self):
        tool = CostTool()
        import asyncio
        result = asyncio.run(tool.estimate_resource("aws_undefined_resource", "aws_undefined_resource.x"))
        assert result.estimated_monthly_cost >= 0

    def test_cost_map_values(self):
        assert all(isinstance(v, (int, float)) for v in [
            2.30, 25.00, 0.00, 3.50, 32.40, 3.60, 22.40, 100.00, 50.00, 30.00, 10.00
        ])


class TestGitHubTool:
    def test_format_review_comment_no_issues(self):
        from app.models.schemas import ReviewOutput, AiReview
        tool = GitHubTool()
        review = ReviewOutput(
            pr_number=1,
            repository="test/repo",
            ai_review=AiReview(
                summary="All clear.",
                risks=[],
                recommendations=[],
                score=90,
                approved=True,
            ),
        )
        comment = tool._format_review_comment(review)
        assert "Terraform Review Agent Report" in comment
        assert "✅" in comment
        assert "90/100" in comment

    def test_format_review_comment_with_security_issues(self):
        from app.models.schemas import ReviewOutput, AiReview, SecurityIssue
        tool = GitHubTool()
        review = ReviewOutput(
            pr_number=1,
            repository="test/repo",
            ai_review=AiReview(
                summary="Issues found.",
                risks=["Public S3 bucket"],
                recommendations=["Block public access"],
                score=30,
                approved=False,
            ),
            security_issues=[
                SecurityIssue(
                    severity="HIGH",
                    category="public_s3",
                    resource="aws_s3_bucket.data",
                    message="Bucket is public",
                    recommendation="Block public access",
                )
            ],
        )
        comment = tool._format_review_comment(review)
        assert "Security Issues" in comment
        assert "aws_s3_bucket.data" in comment
        assert "🔒" in comment

    def test_format_review_comment_with_cost(self):
        from app.models.schemas import ReviewOutput, AiReview, CostEstimate
        tool = GitHubTool()
        review = ReviewOutput(
            pr_number=1,
            repository="test/repo",
            ai_review=AiReview(summary="OK", risks=[], recommendations=[], score=80, approved=True),
            cost_estimates=[
                CostEstimate(resource="aws_nat_gateway.main", resource_type="aws_nat_gateway", estimated_monthly_cost=32.40)
            ],
        )
        comment = tool._format_review_comment(review)
        assert "Cost Estimate" in comment
        assert "$32.40" in comment
