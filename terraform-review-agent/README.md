# Terraform Review Agent

AI-powered infrastructure governance that automatically reviews Terraform PRs for security risks, policy compliance, cost impact, and code quality — for both **GCP and AWS** workloads.

Every PR gets:
- A security scan (public buckets, wildcard IAM, missing encryption)
- OPA policy evaluation against bundled and custom Rego rules
- Cost estimation (Infracost if available, static map fallback)
- A GPT-4o review with a 0–100 score and approve/reject
- A PR comment with the full report
- A GitHub Commit Status that blocks merges when the review fails

---

## Quick Start — Use in any repo in 5 minutes

Add this workflow to `.github/workflows/pr-review.yml`:

```yaml
name: Terraform Review Agent
on:
  pull_request:
    paths: ["**.tf"]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      statuses: write      # required for commit status
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
          GITHUB_PR_NUMBER: ${{ github.event.pull_request.number }}
          GITHUB_SHA: ${{ github.event.pull_request.head.sha }}
          TERRAFORM_DIR: ${{ github.workspace }}
        run: |
          python - <<'PYEOF'
          import asyncio, os, sys
          sys.path.insert(0, os.getcwd())
          from app.models.state import make_initial_state
          from app.workflows.graph import create_review_graph
          async def main():
              initial = make_initial_state()
              initial['pr_number']   = int(os.environ.get('GITHUB_PR_NUMBER') or 0)
              initial['repository']  = os.environ.get('GITHUB_REPOSITORY', '')
              initial['commit_sha']  = os.environ.get('GITHUB_SHA', '')
              initial['terraform_dir'] = os.environ.get('TERRAFORM_DIR', '')
              result = await create_review_graph().ainvoke(dict(initial))
              print('Status:', result.get('status'))
              approved = result.get('ai_review') and result['ai_review'].approved
              sys.exit(0 if approved else 1)
          asyncio.run(main())
          PYEOF
```

Add `OPENAI_API_KEY` as a repository secret. Every PR touching `.tf` files gets reviewed and the merge is blocked until the agent approves it.

---

## Architecture

```
GitHub Pull Request
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Server                            │
│                                                             │
│  POST /review          POST /webhook/github                 │
│  (direct API call)     (HMAC-verified webhook)              │
│         │                       │                           │
│         └──────────┬────────────┘                           │
│                    ▼                                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              LangGraph Workflow Engine               │   │
│  │                                                      │   │
│  │  ┌─────────────┐                                    │   │
│  │  │ terraform    │                                    │   │
│  │  │ plan + JSON  │                                    │   │
│  │  └──────┬──────┘                                    │   │
│  │         │                                            │   │
│  │         ▼                                            │   │
│  │  ┌─────────────┐                                    │   │
│  │  │ prepare OPA │                                    │   │
│  │  │    input    │                                    │   │
│  │  └──────┬──────┘                                    │   │
│  │         │  (parallel fan-out)                        │   │
│  │    ┌────┴────┐         ┌────────────┐               │   │
│  │    ▼         ▼         ▼            ▼               │   │
│  │ security   OPA       cost         (joins)           │   │
│  │  scan    validate  analysis                         │   │
│  │    └────┬────┘         └────────────┘               │   │
│  │         │                                            │   │
│  │         ▼                                            │   │
│  │  ┌─────────────┐                                    │   │
│  │  │  AI review  │ (GPT-4o aggregates all findings)   │   │
│  │  └──────┬──────┘                                    │   │
│  │         │  (parallel fan-out)                        │   │
│  │    ┌────┴────────────┐                              │   │
│  │    ▼                 ▼                              │   │
│  │ PR comment     commit status                        │   │
│  │ (markdown)     (pass/fail)                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Workflow Nodes

| Node | What it does |
|------|-------------|
| `terraform_plan_node` | Runs `terraform init` + `plan`. Also captures `terraform show -json` for structured resource extraction. |
| `prepare_opa_input` | Parses plan JSON (or falls back to stdout regex) into a normalized resource list for OPA. |
| `security_scan_node` | GPT-4o scans the plan for public resources, wildcard IAM, missing encryption, exposed secrets. |
| `opa_validation_node` | Evaluates all `.rego` files in the policy directory against the resource list. |
| `cost_analysis_node` | Tries Infracost CLI first; falls back to a built-in static cost map for GCP + AWS resources. |
| `ai_review_node` | GPT-4o aggregates all findings into a final review with a 0–100 score and approve/reject. |
| `github_comment_node` | Posts a formatted markdown report as a PR comment. |
| `github_status_node` | Sets a GitHub Commit Status (`success`/`failure`) to block or allow the merge. |

---

## Features

### Security
- Detects public GCP storage buckets (`allUsers`, `allAuthenticatedUsers` IAM members)
- Detects AWS S3 public ACLs and open security group rules
- Flags `roles/owner`, `roles/editor`, and wildcard admin grants
- Detects unencrypted EBS volumes and RDS instances
- Flags service account keys (recommends Workload Identity)
- Detects 0.0.0.0/0 firewall ingress rules

### Policy (OPA)
- Ships 4 bundled Rego policy files that work with zero configuration:
  - `gcp_security.rego` — IAM, public access, label enforcement, GKE checks
  - `gcp_cost.rego` — Cloud NAT, oversized VMs, GKE clusters, Cloud SQL
  - `aws_security.rego` — Public S3, IAM users/keys, open SSH/RDP, encryption
  - `aws_cost.rego` — Oversized EC2, RDS, EKS, NAT Gateways
- Custom policies: drop any `.rego` file into `OPA_POLICY_DIR` and they are picked up automatically
- Policy violations are included in the AI review and PR comment

### Cost Estimation
- Uses **Infracost CLI** when installed for real per-SKU pricing
- Falls back to a built-in static cost map with 70+ GCP + AWS resource types
- Marks all static estimates as approximations with a link to the cloud pricing calculator
- Total estimated monthly cost is shown in the PR comment

### GitHub Integration
- Posts a full markdown report as a PR comment (score, security issues, OPA violations, cost breakdown)
- Sets a **GitHub Commit Status** (`terraform-review-agent`) — integrates with branch protection rules
- Verifies `X-Hub-Signature-256` on all webhook payloads (HMAC-SHA256)
- Skips PRs with no `.tf` file changes

### Multi-Cloud
- GCP: `google_*` resources in OPA extraction, cost map, and security prompts
- AWS: `aws_*` resources with the same full pipeline coverage

---

## Setup

### Prerequisites

| Tool | Version | Required |
|------|---------|----------|
| Python | 3.11+ | Yes |
| Terraform | 1.9+ | Yes |
| OPA | 0.68+ | Yes |
| Infracost | any | No (falls back to static map) |
| Redis | 7+ | No (optional state cache) |

### Local Development

```bash
git clone https://github.com/MaripeddiSupraj/ai-agents.git
cd ai-agents/terraform-review-agent

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add OPENAI_API_KEY and GITHUB_TOKEN to .env

# Start the API server
uvicorn app.main:app --reload --port 8000

# Health check
curl http://localhost:8000/health

# Run a review against the sample terraform module
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"directory": "./terraform/sample"}'
```

### Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o` | Model for AI agents |
| `GITHUB_TOKEN` | For PR comments | — | GitHub token with `pull-requests: write` and `statuses: write` |
| `GITHUB_REPOSITORY` | For PR comments | — | `owner/repo` format |
| `GITHUB_PR_NUMBER` | For direct API | — | PR number (auto-set by webhook) |
| `GITHUB_WEBHOOK_SECRET` | For webhooks | — | HMAC secret for validating webhook payloads |
| `TERRAFORM_DIR` | No | `./terraform/sample` | Terraform root module path |
| `OPA_POLICY_DIR` | No | `app/policies` | Directory of `.rego` policy files |
| `INFRACOST_BINARY` | No | `infracost` | Path to infracost CLI |
| `INFRACOST_API_KEY` | No | — | Infracost API key (for CI usage) |
| `GCP_PROJECT_ID` | No | — | GCP project (for future live billing API) |
| `GCP_REGION` | No | `us-central1` | GCP region |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | No | `json` | `json` (production) or `console` (dev) |

### GitHub Actions Setup

1. **Repository secrets** — add `OPENAI_API_KEY` (the GitHub token is auto-injected)

2. **Branch protection** — after the first review runs, enable "Require status checks to pass" and select `terraform-review-agent`

3. **Custom OPA policies** — set `OPA_POLICY_DIR` to a directory in your repo with additional `.rego` files; bundled policies always run alongside them

4. **Infracost** — add `uses: infracost/actions/setup@v3` before the review step and set `INFRACOST_API_KEY`; the agent detects it automatically

---

## API Reference

### `GET /health`

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "redis_connected": false
}
```

### `POST /review`

Run a full review pipeline directly (no webhook, no PR required).

**Request:**
```json
{
  "directory": "./terraform/sample",
  "commit_sha": "abc123def456"
}
```

`commit_sha` is optional — when provided, a GitHub Commit Status is posted.

**Response:** Full `ReviewOutput` including security issues, OPA violations, cost estimates, and AI review.

### `POST /webhook/github`

Receives GitHub `pull_request` webhook events. Validates `X-Hub-Signature-256` when `GITHUB_WEBHOOK_SECRET` is set. Skips events with no `.tf` file changes.

---

## Custom OPA Policies

Drop any `.rego` file into `OPA_POLICY_DIR`. It must export `deny` as a set of violation objects:

```rego
package terraform

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_instance"
    not resource.labels["cost_center"]
    msg := {
        "policy":   "require_cost_center_label",
        "resource": resource.address,
        "message":  "All compute instances must have a cost_center label.",
        "severity": "MEDIUM",
    }
}
```

Each resource in `input.resources` has these fields:

| Field | Example |
|-------|---------|
| `address` | `google_storage_bucket.data` |
| `type` | `google_storage_bucket` |
| `action` | `create`, `update`, `destroy`, `replace` |
| `labels` | `{"environment": "prod", "owner": "platform"}` |
| `member` | `allUsers` (for IAM bindings) |
| `role` | `roles/owner` |
| `machine_type` | `n2-standard-4` |
| `database_version` | `POSTGRES_15` |

---

## Project Structure

```
terraform-review-agent/
├── app/
│   ├── main.py                 # FastAPI entry point, webhook + review endpoints
│   ├── agents/
│   │   ├── security_agent.py   # GPT-4o security scanner
│   │   ├── cost_agent.py       # Infracost + static map cost estimator
│   │   └── review_agent.py     # GPT-4o final review aggregator
│   ├── policies/               # Bundled OPA Rego policies (shipped with agent)
│   │   ├── gcp_security.rego   # GCP IAM, public access, label enforcement
│   │   ├── gcp_cost.rego       # GCP cost control policies
│   │   ├── aws_security.rego   # AWS IAM, S3 ACLs, open ports, encryption
│   │   └── aws_cost.rego       # AWS cost control policies
│   ├── tools/
│   │   ├── terraform_tools.py  # Terraform CLI wrapper (plan + plan -json)
│   │   ├── opa_tools.py        # OPA binary evaluator
│   │   ├── cost_tools.py       # Infracost + static GCP/AWS cost map
│   │   └── github_tools.py     # PR comments + commit status
│   ├── workflows/
│   │   └── graph.py            # LangGraph state machine (8 nodes)
│   ├── prompts/
│   │   ├── security_prompts.py # Multi-cloud security analysis prompts
│   │   ├── review_prompts.py   # Final review generation prompts
│   │   └── cost_prompts.py     # Cost context prompts
│   ├── models/
│   │   ├── config.py           # Pydantic settings with bundled policy default
│   │   ├── schemas.py          # Request/response/state schemas
│   │   └── state.py            # LangGraph ReviewState TypedDict
│   └── utils/
│       ├── logger.py           # Structured logging (structlog)
│       ├── retry.py            # Async retry decorator
│       └── redis_client.py     # Optional Redis state backend
├── terraform/
│   └── sample/
│       ├── main.tf             # Sample GCP Terraform config for testing
│       └── policies/           # Legacy policy dir (still works via OPA_POLICY_DIR)
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── secret.yaml
├── action/
│   └── action.yml              # Reusable GitHub Action definition
├── tests/
│   ├── conftest.py
│   ├── test_main.py            # Webhook signature + endpoint tests
│   ├── test_agents.py          # Security, cost, review agent unit tests
│   ├── test_tools.py           # Terraform, OPA, cost, GitHub tool tests
│   └── test_workflows.py       # Graph structure, state, prompt tests
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Design Decisions

### Why LangGraph?

LangGraph gives us a **typed, async state graph** that maps directly to CI/CD pipeline stages:
- **Conditional branching** — Skip terraform plan when no `.tf` files changed
- **Parallel execution** — Security scan, OPA validation, and cost analysis run concurrently; PR comment and commit status post in parallel
- **Typed state** — `ReviewState` TypedDict validates data between nodes at compile time
- **Async-first** — All nodes are `async`, sharing one event loop with FastAPI

### Why terraform plan -json?

`terraform plan -out=plan.bin && terraform show -json plan.bin` gives structured resource data (addresses, types, before/after values, actions) with no regex fragility. The stdout text plan is kept as context for the GPT-4o security scan, which benefits from the human-readable format.

### Why bundled OPA policies?

Users should get value immediately — before writing any Rego. The 4 bundled files enforce the most common GCP and AWS security and cost baselines. Users can extend or override them by pointing `OPA_POLICY_DIR` at their own directory; the bundled dir is the default.

### Security Model

- Webhook payloads are verified with HMAC-SHA256 (`X-Hub-Signature-256`)
- GitHub Actions expressions are never interpolated into Python strings — passed via `env:` vars
- Terraform runs with `TF_IN_AUTOMATION=true`
- OPA evaluates structured JSON input, not arbitrary HCL
- The GitHub token needs only `pull-requests: write` and `statuses: write`

---

## Running Tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest tests/ -v
# 55 tests, all pass
```

---

## Roadmap

- [ ] **Checkov / tfsec integration** — Static HCL analysis before plan
- [ ] **Drift detection** — Compare planned changes against live cloud state
- [ ] **Historical scoring** — Track PR scores over time, surface trends
- [ ] **Slack/Teams notifications** — Alert on critical findings
- [ ] **Auto-remediation** — Post suggested fixes as PR code suggestions
- [ ] **Azure support** — `azurerm_*` resources in cost map and OPA policies
- [ ] **WebSocket streaming** — Stream workflow progress live to the browser
- [ ] **OpenTelemetry tracing** — End-to-end span visibility across nodes

---

## License

MIT
