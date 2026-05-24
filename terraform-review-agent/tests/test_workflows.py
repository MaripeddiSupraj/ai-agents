from app.models.state import ReviewState, make_initial_state
from app.workflows.graph import create_review_graph


class TestReviewGraph:
    def test_graph_is_compiled(self):
        graph = create_review_graph()
        assert graph is not None
        assert hasattr(graph, "ainvoke")

    def test_graph_has_required_nodes(self):
        graph = create_review_graph()
        node_names = list(graph.nodes.keys())
        expected = [
            "terraform_plan_node",
            "prepare_opa_input",
            "security_scan_node",
            "opa_validation_node",
            "cost_analysis_node",
            "ai_review_node",
            "github_comment_node",
            "github_status_node",
        ]
        for name in expected:
            assert name in node_names, f"Missing node: {name}"

    def test_initial_state_structure(self):
        state = make_initial_state()
        assert state["status"] == "pending"
        assert state["pr_number"] == 0
        assert state["errors"] == []
        assert state["opa_input"] == {"resources": []}
        assert state["security_issues"] == []
        assert state["opa_violations"] == []
        assert state["cost_estimates"] == []
        assert state["ai_review"] is None
        assert state["terraform_dir"] == ""
        assert state["commit_sha"] == ""
        assert state["terraform_plan_json"] == ""

    def test_state_typeddict_keys(self):
        expected_keys = {
            "pr_number", "repository", "pr_title", "pr_body", "changed_files",
            "terraform_dir", "commit_sha",
            "terraform_plan_json",
            "terraform_init_stdout", "terraform_init_stderr",
            "terraform_plan_stdout", "terraform_plan_stderr",
            "terraform_plan_exit_code", "terraform_plan_response",
            "security_issues", "opa_violations", "cost_estimates",
            "ai_review", "opa_input",
            "review_comment_id", "status", "errors",
        }
        keys = set(ReviewState.__annotations__.keys())
        assert keys == expected_keys, f"Missing keys: {expected_keys - keys}"

    def test_conditional_edge_logic(self):
        from app.workflows.graph import should_run_plan, check_plan_result
        import asyncio

        state = make_initial_state()
        state["changed_files"] = ["main.tf"]
        result = asyncio.run(should_run_plan(state))
        assert result == "continue"

        state["changed_files"] = ["README.md"]
        result = asyncio.run(should_run_plan(state))
        assert result == "skip_plan"

    def test_plan_failed_edge(self):
        from app.workflows.graph import check_plan_result
        import asyncio

        state = make_initial_state()
        result = asyncio.run(check_plan_result(state))
        assert result == "failed"

        state["terraform_plan_exit_code"] = 0
        result = asyncio.run(check_plan_result(state))
        assert result == "continue"

    def test_extract_opa_resources_from_json(self):
        from app.workflows.graph import _extract_opa_resources_from_json
        import json

        plan_json = json.dumps({
            "resource_changes": [
                {
                    "address": "google_storage_bucket.data",
                    "type": "google_storage_bucket",
                    "change": {
                        "actions": ["create"],
                        "after": {
                            "labels": {"environment": "prod", "owner": "team"},
                            "member": "",
                            "role": "",
                        },
                    },
                },
                {
                    "address": "aws_instance.web",
                    "type": "aws_instance",
                    "change": {
                        "actions": ["no-op"],
                        "after": {},
                    },
                },
            ]
        })
        resources = _extract_opa_resources_from_json(plan_json)
        # no-op resources should be skipped
        assert len(resources) == 1
        assert resources[0]["address"] == "google_storage_bucket.data"
        assert resources[0]["action"] == "create"
        assert resources[0]["labels"]["environment"] == "prod"

    def test_extract_opa_resources_from_json_multi_action(self):
        from app.workflows.graph import _extract_opa_resources_from_json
        import json

        plan_json = json.dumps({
            "resource_changes": [
                {
                    "address": "aws_instance.web",
                    "type": "aws_instance",
                    "change": {
                        "actions": ["delete", "create"],
                        "after": {"instance_type": "t3.micro"},
                    },
                }
            ]
        })
        resources = _extract_opa_resources_from_json(plan_json)
        assert len(resources) == 1
        assert resources[0]["action"] == "replace"
        assert resources[0]["machine_type"] == "t3.micro"


class TestPrompts:
    def test_security_prompt_has_required_sections(self):
        from app.prompts.security_prompts import SECURITY_SYSTEM_PROMPT, SECURITY_USER_PROMPT
        assert "public" in SECURITY_SYSTEM_PROMPT.lower()
        assert "iam" in SECURITY_SYSTEM_PROMPT.lower()
        assert "tags" in SECURITY_SYSTEM_PROMPT.lower()
        assert "destructive" in SECURITY_SYSTEM_PROMPT.lower()
        assert "{plan_output}" in SECURITY_USER_PROMPT
        assert "{changed_files}" in SECURITY_USER_PROMPT

    def test_review_prompt_has_required_sections(self):
        from app.prompts.review_prompts import REVIEW_SYSTEM_PROMPT, REVIEW_USER_PROMPT
        assert "security" in REVIEW_SYSTEM_PROMPT.lower()
        assert "opa" in REVIEW_SYSTEM_PROMPT.lower()
        assert "cost" in REVIEW_SYSTEM_PROMPT.lower()
        assert "approved" in REVIEW_SYSTEM_PROMPT.lower()

    def test_cost_prompt_has_required_sections(self):
        from app.prompts.cost_prompts import COST_SYSTEM_PROMPT, COST_USER_PROMPT
        assert "cost" in COST_SYSTEM_PROMPT.lower()
        assert "finops" in COST_SYSTEM_PROMPT.lower()
        assert "{plan_output}" in COST_USER_PROMPT
        assert "{cost_estimates}" in COST_USER_PROMPT


class TestSchemas:
    def test_security_issue_defaults(self):
        from app.models.schemas import SecurityIssue
        issue = SecurityIssue(severity="HIGH", category="test", resource="r", message="m", recommendation="fix")
        assert issue.severity == "HIGH"
        assert issue.category == "test"

    def test_review_output_defaults(self):
        from app.models.schemas import ReviewOutput
        output = ReviewOutput()
        assert output.status == "completed"
        assert output.errors == []
        assert output.security_issues == []

    def test_ai_review_defaults(self):
        from app.models.schemas import AiReview
        review = AiReview(summary="test")
        assert review.score == 0
        assert review.approved is False
        assert review.risks == []
