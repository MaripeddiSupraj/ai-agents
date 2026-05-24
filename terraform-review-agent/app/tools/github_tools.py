from typing import Optional
from github import Github
from github.IssueComment import IssueComment

from app.models.config import get_settings
from app.models.schemas import ReviewOutput
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

    async def set_commit_status(
        self,
        commit_sha: str,
        approved: bool,
        score: int,
        description: str = "",
    ) -> bool:
        if not self._token or not commit_sha:
            logger.info("commit_status_skipped", reason="no token or sha")
            return False
        try:
            state = "success" if approved else "failure"
            desc = description or (
                f"Score: {score}/100 — {'Approved' if approved else 'Changes requested'}"
            )
            client = self._get_client()
            repo = client.get_repo(self._repository)
            commit = repo.get_commit(commit_sha)
            commit.create_status(
                state=state,
                description=desc[:140],
                context="terraform-review-agent",
                target_url="",
            )
            logger.info(
                "commit_status_set",
                sha=commit_sha[:8],
                state=state,
                score=score,
            )
            return True
        except Exception as e:
            logger.error("commit_status_failed", error=str(e))
            return False

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

    # Severity ordering and emoji mapping
    _SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢", "INFO": "⚪"}
    _SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

    def _sev_emoji(self, sev: str) -> str:
        return self._SEV_EMOJI.get(sev.upper(), "⚪")

    def _format_review_comment(self, review: ReviewOutput) -> str:
        ai = review.ai_review
        score = ai.score if ai else 0
        approved = ai.approved if ai else False
        verdict = "✅ Approved" if approved else "❌ Changes Requested"
        score_bar = self._score_bar(score)

        lines: list[str] = []

        # ── Header ────────────────────────────────────────────────────────────
        lines += [
            f"## 🤖 Terraform Review &nbsp;·&nbsp; {verdict}",
            "",
            f"{score_bar} &nbsp; **{score}/100**",
            "",
        ]

        if ai and ai.summary:
            lines += [f"> {ai.summary}", ""]

        # ── At a Glance ───────────────────────────────────────────────────────
        cost_total = sum(c.estimated_monthly_cost for c in review.cost_estimates)
        sec_counts = self._count_by_severity(
            [i.severity for i in review.security_issues]
        )
        opa_counts = self._count_by_severity(
            [v.severity for v in review.opa_violations]
        )
        sec_summary = self._severity_summary(sec_counts) or "✅ None"
        opa_summary = self._severity_summary(opa_counts) or "✅ None"
        cost_str = f"~${cost_total:.0f}/mo" if cost_total else "—"

        lines += [
            "---",
            "",
            "### 📊 Overview",
            "",
            "| Security Issues | OPA Violations | Est. Cost |",
            "|----------------|---------------|-----------|",
            f"| {sec_summary} | {opa_summary} | {cost_str} |",
            "",
        ]

        # ── Security Findings ─────────────────────────────────────────────────
        if review.security_issues:
            sorted_issues = sorted(
                review.security_issues,
                key=lambda i: self._SEV_ORDER.get(i.severity.upper(), 9),
            )
            lines += ["---", "", "### 🔒 Security Findings", ""]
            current_sev = None
            for issue in sorted_issues:
                sev = issue.severity.upper()
                if sev != current_sev:
                    current_sev = sev
                    lines += [f"**{self._sev_emoji(sev)} {sev}**", ""]
                    lines += [
                        "| Resource | Issue | Recommendation |",
                        "|----------|-------|----------------|",
                    ]
                lines.append(
                    f"| `{issue.resource}` | {issue.message} | {issue.recommendation} |"
                )
            lines.append("")

        # ── AI Risks & Recommendations ────────────────────────────────────────
        if ai and (ai.risks or ai.recommendations):
            lines += ["---", "", "### 💡 AI Analysis", ""]
            if ai.risks:
                lines.append("**Risks**")
                lines.append("")
                for r in ai.risks:
                    lines.append(f"- {r}")
                lines.append("")
            if ai.recommendations:
                lines.append("**Recommendations**")
                lines.append("")
                for r in ai.recommendations:
                    lines.append(f"- {r}")
                lines.append("")

        # ── Cost Breakdown ────────────────────────────────────────────────────
        billable = [c for c in review.cost_estimates if c.estimated_monthly_cost > 0]
        if billable:
            billable_sorted = sorted(
                billable, key=lambda c: c.estimated_monthly_cost, reverse=True
            )
            lines += ["---", "", "### 💰 Cost Breakdown", ""]
            lines += [
                "| Resource | Est. Monthly Cost |",
                "|----------|------------------|",
            ]
            for c in billable_sorted:
                flag = " ⚠️" if c.estimated_monthly_cost >= 30 else ""
                lines.append(f"| `{c.resource}` | ${c.estimated_monthly_cost:.2f}{flag} |")
            lines += [f"| **Total** | **${cost_total:.2f}/mo** |", ""]
            lines += [
                "> _Cost estimates are approximations. Verify with the_",
                "> _[AWS Pricing Calculator](https://calculator.aws) or_",
                "> _[GCP Pricing Calculator](https://cloud.google.com/products/calculator)._",
                "",
            ]

        # ── OPA Violations (collapsible) ──────────────────────────────────────
        if review.opa_violations:
            sorted_v = sorted(
                review.opa_violations,
                key=lambda v: self._SEV_ORDER.get(v.severity.upper(), 9),
            )
            lines += ["---", ""]
            lines.append(
                f"<details>\n<summary>📋 OPA Policy Violations &nbsp;·&nbsp;"
                f" {len(sorted_v)} found (click to expand)</summary>\n"
            )
            lines += [
                "| Sev | Policy | Resource | Message |",
                "|-----|--------|----------|---------|",
            ]
            for v in sorted_v:
                emoji = self._sev_emoji(v.severity)
                lines.append(
                    f"| {emoji} | `{v.policy}` | `{v.resource}` | {v.message} |"
                )
            lines += ["", "</details>", ""]

        # ── Errors ────────────────────────────────────────────────────────────
        if review.errors:
            lines += ["---", "", "### ⚠️ Errors", ""]
            for err in review.errors:
                lines.append(f"- `{err}`")
            lines.append("")

        # ── Footer ────────────────────────────────────────────────────────────
        lines += [
            "---",
            "<sub>🤖 [Terraform Review Agent](https://github.com/MaripeddiSupraj/ai-agents/tree/master/terraform-review-agent)"
            " &nbsp;·&nbsp; Powered by OpenAI + OPA</sub>",
        ]

        return "\n".join(lines)

    def _score_bar(self, score: int) -> str:
        filled = round(score / 10)
        bar = "█" * filled + "░" * (10 - filled)
        if score >= 80:
            return f"`{bar}`"
        if score >= 50:
            return f"`{bar}`"
        return f"`{bar}`"

    def _count_by_severity(self, severities: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in severities:
            counts[s.upper()] = counts.get(s.upper(), 0) + 1
        return counts

    def _severity_summary(self, counts: dict[str, int]) -> str:
        parts = []
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if counts.get(sev, 0):
                parts.append(f"{self._sev_emoji(sev)} {counts[sev]} {sev}")
        return " &nbsp; ".join(parts)
