import pytest
from unittest.mock import patch

from app.agents.cost_agent import CostAnalysisAgent


def _make_security_agent():
    with patch("app.agents.security_agent.ChatOpenAI"):
        from app.agents.security_agent import SecurityScanAgent
        return SecurityScanAgent()


def _make_review_agent():
    with patch("app.agents.review_agent.ChatOpenAI"):
        from app.agents.review_agent import AIReviewAgent
        return AIReviewAgent()


class TestSecurityScanAgent:
    @pytest.mark.asyncio
    async def test_skip_when_no_plan(self):
        agent = _make_security_agent()
        state = {"terraform_plan_stdout": "", "changed_files": []}
        result = await agent(state)
        assert result == {"security_issues": []}

    def test_parse_response_valid_json(self):
        agent = _make_security_agent()
        response = '[{"severity":"HIGH","category":"public_s3","resource":"google_storage_bucket.x","message":"test","recommendation":"fix"}]'
        issues = agent._parse_response(response)
        assert len(issues) == 1
        assert issues[0].severity == "HIGH"
        assert issues[0].category == "public_s3"

    def test_parse_response_with_code_fence(self):
        agent = _make_security_agent()
        response = '```json\n[{"severity":"HIGH","category":"test","resource":"r","message":"m","recommendation":"fix"}]\n```'
        issues = agent._parse_response(response)
        assert len(issues) == 1

    def test_parse_response_dict_wrapped(self):
        agent = _make_security_agent()
        response = '{"security_issues":[{"severity":"HIGH","category":"test","resource":"r","message":"m","recommendation":"fix"}]}'
        issues = agent._parse_response(response)
        assert len(issues) == 1

    def test_parse_response_invalid_json(self):
        agent = _make_security_agent()
        issues = agent._parse_response("not json")
        assert issues == []


class TestCostAnalysisAgent:
    @pytest.mark.asyncio
    async def test_skip_when_no_plan(self):
        agent = CostAnalysisAgent()
        state = {"terraform_plan_stdout": ""}
        result = await agent(state)
        assert result == {"cost_estimates": []}

    def test_extract_resource_types(self):
        agent = CostAnalysisAgent()
        plan = (
            '  # google_storage_bucket.x will be created\n'
            '  + resource "google_storage_bucket" "x" {\n'
            '  # google_firestore_database.y will be created\n'
        )
        types = agent._extract_resource_types(plan)
        assert len(types) >= 2
        assert ("google_storage_bucket", "google_storage_bucket.x") in types


class TestAIReviewAgent:
    @pytest.mark.asyncio
    async def test_skip_when_no_plan(self):
        agent = _make_review_agent()
        state = {
            "terraform_plan_stdout": "",
            "security_issues": [],
            "opa_violations": [],
            "cost_estimates": [],
        }
        result = await agent(state)
        review = result.get("ai_review")
        assert review is not None
        assert review.score == 50
        assert review.approved is False

    def test_parse_response_valid(self):
        agent = _make_review_agent()
        response = '{"summary":"Good","risks":[],"recommendations":["add tags"],"score":85,"approved":true}'
        review = agent._parse_response(response)
        assert review.summary == "Good"
        assert review.score == 85
        assert review.approved is True

    def test_parse_response_invalid(self):
        agent = _make_review_agent()
        review = agent._parse_response("bad json")
        assert review.approved is False
        assert review.score == 0
