# AI Agents

Collection of AI-powered agents for automating infrastructure, security, and DevOps workflows.

## Agents

| Agent | Description | Status |
|-------|-------------|--------|
| [terraform-review-agent](./terraform-review-agent/) | Reviews Terraform PRs for security, policy, cost, and AI-approval | Active |

## terraform-review-agent Quick Start

Add this to any repo with Terraform code (`.github/workflows/pr-review.yml`):

```yaml
- uses: actions/checkout@v4
- uses: actions/checkout@v4
  with:
    repository: MaripeddiSupraj/ai-agents
    path: ai-agents
- working-directory: ai-agents/terraform-review-agent
  run: pip install -r requirements.txt
- working-directory: ai-agents/terraform-review-agent
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    TERRAFORM_DIR: ${{ github.workspace }}
  run: python -c "from app.workflows.graph import create_review_graph; import asyncio; asyncio.run(create_review_graph().ainvoke(...))"
```

See [full workflow](./terraform-review-agent/README.md#quick-start) and [demo repo](https://github.com/MaripeddiSupraj/demo-tf-review).
