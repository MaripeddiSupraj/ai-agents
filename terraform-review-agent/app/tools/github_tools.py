from typing import Optional
from github import Github, GithubIntegration
from github.IssueComment import IssueComment

from app.models.config import get_settings
from app.models.schemas import (
    ReviewOutput,
    SecurityIssue,
    OpaViolation,
    CostEstimate,
    AiReview,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GitHubTool:
    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.github_token
        self._repository = settings.github_repository
        self._client: Optional[Github] = None

    def _get_client(self) -> Github:
        if self._client is None:
            self._client = Github(self._token)
        return self._client

    async def post_pr_comment(
        self,
        pr_number: int,
        review: ReviewOutput,
    ) -> Optional[int]:
        if not self._token:
            logger.warning("github_token_not_configured")
            return None

        try:
            body = self._format_review_comment(review)
            client = self._get_client()
            repo = client.get_repo(self._repository)
            pr = repo.get_pull(pr_number)
            comment: IssueComment = pr.create_issue_comment(body)
            logger.info(
                "pr_comment_posted",
                pr_number=pr_number,
                comment_id=comment.id,
            )
            return comment.id
        except Exception as e:
            logger.error(
                "pr_comment_failed",
                pr_number=pr_number,
                error=str(e),
            )
            return None

    async def update_pr_comment(
        self, comment_id: int, review: ReviewOutput
    ) -> bool:
        if not self._token:
            return False
        try:
            body = self._format_review_comment(review)
            client = self._get_client()
            repo = client.get_repo(self._repository)
            comment = repo.get_issue_comment(comment_id)
            comment.edit(body)
            logger.info("pr_comment_updated", comment_id=comment_id)
            return True
        except Exception as e:
            logger.error("pr_comment_update_failed", error=str(e))
            return False

    def _format_review_comment(self, review: ReviewOutput) -> str:
        lines: list[str] = [
            "## 🤖 Terraform Review Agent Report",
            "",
            f"**Status:** {review.status.upper()}",
            f"**Score:** {review.ai_review.score if review.ai_review else 'N/A'}/100",
            f"**Approved:** {'✅' if review.ai_review and review.ai_review.approved else '❌'}",
            "",
        ]

        if review.ai_review:
            lines.append("### Summary")
            lines.append("")
            lines.append(review.ai_review.summary)
            lines.append("")

            if review.ai_review.risks:
                lines.append("### ⚠️ Risks Detected")
                lines.append("")
                for risk in review.ai_review.risks:
                    lines.append(f"- {risk}")
                lines.append("")

            if review.ai_review.recommendations:
                lines.append("### 💡 Recommendations")
                lines.append("")
                for rec in review.ai_review.recommendations:
                    lines.append(f"- {rec}")
                lines.append("")

        if review.security_issues:
            lines.append("### 🔒 Security Issues")
            lines.append("")
            lines.append("| Severity | Category | Resource | Message |")
            lines.append("|----------|----------|----------|---------|")
            for issue in review.security_issues:
                lines.append(
                    f"| {issue.severity} | {issue.category} | `{issue.resource}` | {issue.message} |"
                )
            lines.append("")

        if review.opa_violations:
            lines.append("### 📋 OPA Policy Violations")
            lines.append("")
            lines.append("| Policy | Resource | Message | Severity |")
            lines.append("|--------|----------|---------|----------|")
            for v in review.opa_violations:
                lines.append(
                    f"| {v.policy} | `{v.resource}` | {v.message} | {v.severity} |"
                )
            lines.append("")

        if review.cost_estimates:
            lines.append("### 💰 Cost Estimate (Monthly)")
            lines.append("")
            lines.append("| Resource | Type | Est. Cost |")
            lines.append("|----------|------|-----------|")
            total = 0.0
            for cost in review.cost_estimates:
                total += cost.estimated_monthly_cost
                lines.append(
                    f"| `{cost.resource}` | {cost.resource_type} | ${cost.estimated_monthly_cost:.2f} |"
                )
            lines.append(f"| **Total** | | **${total:.2f}** |")
            lines.append("")

        if review.errors:
            lines.append("### ❌ Errors")
            lines.append("")
            for err in review.errors:
                lines.append(f"- {err}")
            lines.append("")

        lines.append("---")
        lines.append(
            "_Generated by [Terraform Review Agent](https://github.com/your-org/terraform-review-agent)_"
        )
        lines.append("")

        return "\n".join(lines)
