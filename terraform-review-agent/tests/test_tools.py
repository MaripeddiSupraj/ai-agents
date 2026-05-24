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
        plan = (
            '  # google_storage_bucket.example will be created\n'
            '  + resource "google_storage_bucket" "example" {\n'
            '  # google_storage_bucket.other will be destroyed\n'
            '  - resource "google_storage_bucket" "other" {\n'
        )
        result = tool.parse_plan_resources(plan)
        assert len(result) == 4
        assert result[0]["action"] == "create"
        assert result[1]["address"] == "google_storage_bucket.example"
        assert result[3]["action"] == "destroy"

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

    @pytest.mark.asyncio
    async def test_plan_json_returns_empty_on_binary_not_found(self):
        tool = TerraformTool(work_dir="/tmp")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.plan_json()
            assert result == ""


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
        raw = '{"result":[{"expressions":[{"value":[{"policy":"test","resource":"google_storage_bucket.x","message":"test violation","severity":"HIGH"}]}]}]}'
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
        result = asyncio.run(tool.estimate_resource("google_storage_bucket", "google_storage_bucket.data"))
        assert result.resource_type == "google_storage_bucket"
        assert result.estimated_monthly_cost >= 0
        assert result.is_estimate is True

    def test_estimate_unknown_resource(self):
        tool = CostTool()
        import asyncio
        result = asyncio.run(tool.estimate_resource("google_undefined_resource", "google_undefined_resource.x"))
        assert result.estimated_monthly_cost >= 0
        assert result.is_estimate is True

    def test_cost_map_values(self):
        from app.tools.cost_tools import _RESOURCE_COST_MAP
        assert all(isinstance(v, (int, float)) for v in _RESOURCE_COST_MAP.values())

    def test_cost_map_has_aws_resources(self):
        from app.tools.cost_tools import _RESOURCE_COST_MAP
        aws_keys = [k for k in _RESOURCE_COST_MAP if k.startswith("aws_")]
        assert len(aws_keys) >= 5

    def test_cost_details_honest_language(self):
        tool = CostTool()
        details = tool._build_details("google_compute_instance", 30.0)
        assert "approximation" in details or "estimate" in details.lower() or "~$" in details

    def test_cost_details_zero_cost(self):
        tool = CostTool()
        details = tool._build_details("google_pubsub_topic", 0.0)
        assert "usage" in details.lower() or "no direct cost" in details.lower()

    def test_cost_details_aws_mentions_aws_calculator(self):
        tool = CostTool()
        details = tool._build_details("aws_instance", 30.0)
        assert "AWS" in details

    @pytest.mark.asyncio
    async def test_infracost_returns_empty_when_not_installed(self):
        tool = CostTool()
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.run_infracost("/tmp")
            assert result == []

    def test_parse_infracost_output(self):
        tool = CostTool()
        data = {
            "projects": [{
                "breakdown": {
                    "resources": [
                        {"name": "aws_instance.web", "monthlyCost": "45.60"},
                        {"name": "aws_db_instance.main", "monthlyCost": "120.00"},
                    ]
                }
            }]
        }
        estimates = tool._parse_infracost_output(data)
        assert len(estimates) == 2
        assert estimates[0].resource == "aws_instance.web"
        assert estimates[0].estimated_monthly_cost == 45.60
        assert estimates[0].is_estimate is False


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
        assert "Terraform Review" in comment
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
                    resource="google_storage_bucket.data",
                    message="Bucket is public",
                    recommendation="Block public access",
                )
            ],
        )
        comment = tool._format_review_comment(review)
        assert "Security Findings" in comment
        assert "google_storage_bucket.data" in comment
        assert "🔒" in comment

    def test_format_review_comment_with_cost(self):
        from app.models.schemas import ReviewOutput, AiReview, CostEstimate
        tool = GitHubTool()
        review = ReviewOutput(
            pr_number=1,
            repository="test/repo",
            ai_review=AiReview(summary="OK", risks=[], recommendations=[], score=80, approved=True),
            cost_estimates=[
                CostEstimate(resource="google_compute_router_nat.main", resource_type="google_compute_router_nat", estimated_monthly_cost=32.40)
            ],
        )
        comment = tool._format_review_comment(review)
        assert "Cost Breakdown" in comment
        assert "$32.40" in comment

    @pytest.mark.asyncio
    async def test_set_commit_status_skips_without_token(self):
        tool = GitHubTool()
        tool._token = ""
        result = await tool.set_commit_status("abc123", approved=True, score=90)
        assert result is False

    @pytest.mark.asyncio
    async def test_set_commit_status_skips_without_sha(self):
        tool = GitHubTool()
        tool._token = "fake-token"
        result = await tool.set_commit_status("", approved=True, score=90)
        assert result is False
