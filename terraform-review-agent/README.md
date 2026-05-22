# Terraform Review Agent

AI-powered infrastructure governance platform that automatically reviews Terraform PRs for security risks, policy compliance, cost impact, and code quality.

## Quick Start — Use in any repo

Add this workflow to `.github/workflows/pr-review.yml` in any repo with Terraform code:

```yaml
name: Terraform Review Agent
on: pull_request
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: MaripeddiSupraj/ai-agents
          path: ai-agents
          fetch-depth: 1
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.9.0
      - uses: open-policy-agent/setup-opa@v2
        with:
          version: 1.0.0
      - name: Install agent
        working-directory: ai-agents/terraform-review-agent
        run: pip install -r requirements.txt
      - name: Run review
        working-directory: ai-agents/terraform-review-agent
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          TERRAFORM_DIR: ${{ github.workspace }}
        run: |
          python -c "
          import asyncio, os, sys; sys.path.insert(0, os.getcwd())
          from app.models.state import make_initial_state
          from app.workflows.graph import create_review_graph
          async def main():
              initial = make_initial_state()
              initial['pr_number'] = ${{ github.event.pull_request.number }}
              initial['repository'] = '${{ github.repository }}'
              result = await create_review_graph().ainvoke(dict(initial))
              print('Status:', result.get('status'))
          asyncio.run(main())
          "
```

Then add `OPENAI_API_KEY` as a repo secret. Every PR with `.tf` changes gets reviewed automatically.

For a complete working example, see [demo-tf-review](https://github.com/MaripeddiSupraj/demo-tf-review).

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    GitHub PR Webhook                      │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│                    FastAPI Server                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │             LangGraph Workflow Engine               │  │
│  │                                                     │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐        │  │
│  │  │ Terraform │  │ Security │  │   OPA    │        │  │
│  │  │   Plan    │──▶  Scan    │──▶ Validate │        │  │
│  │  │   Node    │  │   Node   │  │   Node   │        │  │
│  │  └──────────┘  └──────────┘  └──────────┘        │  │
│  │                      │              │              │  │
│  │                      ▼              ▼              │  │
│  │                 ┌──────────┐  ┌──────────┐        │  │
│  │                 │   Cost   │  │   AI     │        │  │
│  │                 │ Analysis │─▶│  Review  │        │  │
│  │                 │   Node   │  │   Node   │        │  │
│  │                 └──────────┘  └──────────┘        │  │
│  │                                     │              │  │
│  │                                     ▼              │  │
│  │                              ┌──────────┐         │  │
│  │                              │  GitHub  │         │  │
│  │                              │ Comment  │         │  │
│  │                              │   Node   │         │  │
│  │                              └──────────┘         │  │
│  └────────────────────────────────────────────────────┘  │
│                          │                                │
│                          ▼                                │
│                    ┌──────────┐                           │
│                    │  Redis   │                           │
│                    │  State   │                           │
│                    │  Memory  │                           │
│                    └──────────┘                           │
└──────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Gateway** | FastAPI | HTTP endpoints for reviews and webhooks |
| **Workflow Engine** | LangGraph | State-machine orchestration of review steps |
| **Terraform Runner** | Terraform CLI | Executes `init` + `plan` with structured output |
| **Security Scanner** | GPT-4o via LangChain | Detects public resources, wildcard IAM, missing tags |
| **OPA Engine** | Open Policy Agent | Rego policy evaluation against plan resources |
| **Cost Estimator** | boto3 + GPT-4o | Approximate monthly cost using AWS Pricing API |
| **AI Reviewer** | GPT-4o | Aggregates findings into a final review with score |
| **PR Commenter** | PyGithub | Posts formatted review comments on GitHub PRs |
| **State Cache** | Redis | Optional workflow state persistence |

## Features

- **Automated Terraform Plan Review** — Runs `terraform init` and `terraform plan` on every PR
- **Security Risk Detection** — Identifies public S3 buckets, wildcard IAM policies, missing encryption, exposed secrets
- **OPA Policy Validation** — Evaluates custom Rego policies for compliance (tagging, cost control, security baselines)
- **GCP Cost Estimation** — Estimates monthly cost impact using GCP Cloud Billing API and known rate cards
- **AI-Powered Review Summaries** — GPT-4o generates concise, actionable review comments with a risk score
- **GitHub PR Integration** — Automatically posts review comments on PRs with markdown-formatted reports
- **Destructive Change Detection** — Flags resources being replaced or destroyed
- **Parallel Workflow Execution** — Security scan, OPA validation, and cost analysis run concurrently via LangGraph

## Setup

### Prerequisites

- Python 3.11+
- Terraform 1.9+ ([install](https://developer.hashicorp.com/terraform/downloads))
- OPA 0.68+ ([install](https://www.openpolicyagent.org/docs/latest/#running-opa))
- Redis 7+ (optional, for persistent state)
- OpenAI API key

### Local Development

```bash
# Clone the repository
git clone https://github.com/your-org/terraform-review-agent.git
cd terraform-review-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your OpenAI API key and GitHub token

# Run the API server
uvicorn app.main:app --reload --port 8000

# Test health endpoint
curl http://localhost:8000/health

# Run a review
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"directory": "./terraform/sample"}'
```

### Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o` | Model for AI review |
| `GITHUB_TOKEN` | For PRs | - | GitHub personal access token |
| `GITHUB_REPOSITORY` | For PRs | - | `owner/repo` format |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `TERRAFORM_DIR` | No | `./terraform/sample` | Terraform root module |
| `OPA_POLICY_DIR` | No | `./terraform/sample/policies` | Rego policy directory |
| `GCP_PROJECT_ID` | For costs | - | GCP project for billing API |
| `GCP_REGION` | No | `us-central1` | GCP region for pricing |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `LOG_FORMAT` | No | `json` | `json` or `console` |

## GitHub Actions Setup

1. Add the following secrets to your repository:
   - `OPENAI_API_KEY` — Your OpenAI API key
   - `GITHUB_TOKEN` — Default `${{ secrets.GITHUB_TOKEN }}` is auto-injected

2. The workflow `.github/workflows/pr-review.yml` triggers on PRs affecting `.tf` files.

3. The workflow:
   - Checks out code
   - Sets up Python, Terraform, and OPA
   - Installs dependencies
   - Runs the LangGraph review workflow
   - Posts a summary comment on the PR

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, or local kind/minikube)
- `kubectl` configured
- Redis running in cluster (or use a managed Redis)

### Deploy

```bash
# Create namespace
kubectl create namespace terraform-review

# Deploy Redis
kubectl apply -f k8s/service.yaml -n terraform-review

# Create ConfigMap
kubectl apply -f k8s/configmap.yaml -n terraform-review

# Create Secret (edit with real values first)
kubectl apply -f k8s/secret.yaml -n terraform-review

# Deploy the application
kubectl apply -f k8s/deployment.yaml -n terraform-review

# Check status
kubectl get pods -n terraform-review -w
```

### Scaling

The deployment is configured with 2 replicas and a rolling update strategy. Scale as needed:

```bash
kubectl scale deployment terraform-review-agent --replicas=5 -n terraform-review
```

### Health Checks

- Liveness probe: `GET /health` — fails after 3 retries, pod restarts
- Readiness probe: `GET /health` — pod receives traffic only when healthy

## API Reference

### `GET /health`

System health check.

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "redis_connected": true
}
```

### `POST /review`

Run a full Terraform review pipeline.

**Request:**
```json
{
  "directory": "./terraform/sample"
}
```

**Response:** `ReviewOutput` (see `app/models/schemas.py`)

### `POST /webhook/github`

GitHub webhook receiver for automatic PR reviews.

## Project Structure

```
terraform-review-agent/
├── app/
│   ├── main.py                 # FastAPI entry point
│   ├── agents/
│   │   ├── security_agent.py   # LLM-powered security scanner
│   │   ├── cost_agent.py       # Cost analysis agent
│   │   └── review_agent.py     # AI review summarizer
│   ├── tools/
│   │   ├── terraform_tools.py  # Terraform CLI wrapper
│   │   ├── opa_tools.py        # OPA policy evaluator
│   │   ├── cost_tools.py       # AWS pricing estimator
│   │   └── github_tools.py     # GitHub API client
│   ├── workflows/
│   │   └── graph.py            # LangGraph state machine
│   ├── prompts/
│   │   ├── security_prompts.py # Security analysis prompts
│   │   ├── review_prompts.py   # Review generation prompts
│   │   └── cost_prompts.py     # Cost analysis prompts
│   ├── models/
│   │   ├── config.py           # Pydantic settings
│   │   ├── schemas.py          # Request/response schemas
│   │   └── state.py            # LangGraph state model
│   └── utils/
│       ├── logger.py           # Structured logging
│       ├── retry.py            # Async retry decorator
│       └── redis_client.py     # Redis state backend
├── terraform/
│   └── sample/
│       ├── main.tf             # Sample Terraform configuration
│       └── policies/
│           ├── security.rego   # Security OPA policies
│           └── cost.rego       # Cost control OPA policies
├── k8s/
│   ├── deployment.yaml         # Kubernetes Deployment
│   ├── service.yaml            # Kubernetes Services
│   ├── configmap.yaml          # Configuration
│   └── secret.yaml             # Secrets template
├── .github/workflows/
│   └── pr-review.yml           # GitHub Actions workflow
├── tests/
│   ├── test_agents.py
│   ├── test_tools.py
│   └── test_workflows.py
├── Dockerfile                  # Multi-stage build
├── requirements.txt
└── .env.example
```

## Design Decisions

### Why LangGraph?

LangGraph provides a **typed state graph** that maps directly to CI/CD pipeline stages. Unlike simple DAG runners (Airflow, Prefect), LangGraph is lightweight, embeds directly in the Python process, and supports:

- **Conditional branching** — Skip terraform plan when no `.tf` files changed
- **Parallel execution** — Security scan, OPA, and cost analysis run concurrently after plan
- **Typed state** — Pydantic models validate data flowing between nodes at compile time
- **Async-first** — All nodes are async, maximizing throughput in the web server

### Why Not a Monolithic Script?

Production infrastructure review needs **observability, reliability, and extensibility**:

- Each review step is a separate module with its own error handling, retry logic, and logging
- Adding a new check (e.g., `checkov` integration) means adding a node to the graph — no refactoring
- The webhook endpoint means this runs as a **service**, not a one-off script
- Stateless design means horizontal scaling with Kubernetes is trivial

### Security Model

- Terraform runs with `TF_IN_AUTOMATION=true` to suppress interactive prompts
- OPA policies are sandboxed and evaluated against a structured input (not arbitrary HCL)
- The container runs as non-root with a read-only filesystem
- Secrets are injected via Kubernetes Secrets (or environment variables for local dev)
- The GitHub token has minimal permissions (write PR comments, read PR metadata)

## Future Improvements

- [ ] **Checkov / tfsec integration** — Static analysis of HCL files before plan
- [ ] **Drift detection** — Compare planned state against live AWS resources
- [ ] **Slack/Teams notifications** — Alert teams when high-risk changes are proposed
- [ ] **Custom policy-as-code UI** — Web UI for managing Rego policies
- [ ] **Multi-cloud support** — AWS and Azure pricing estimation
- [ ] **Terratest integration** — Automated infrastructure testing in review pipeline
- [ ] **Cost history dashboard** — Track cost impact across PRs over time
- [ ] **Auto-remediation** — Post suggested `terraform plan` changes as PR fix suggestions
- [ ] **WebSocket streaming** — Stream workflow progress to the PR in real-time
- [ ] **OpenTelemetry tracing** — End-to-end traceability across workflow nodes

## License

MIT
