FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG TERRAFORM_VERSION=1.9.0
RUN curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && terraform --version

ARG OPA_VERSION=0.68.0
RUN curl -fsSL "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_amd64_static" \
    -o /usr/local/bin/opa \
    && chmod +x /usr/local/bin/opa \
    && opa version

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY --from=builder /root/.local /usr/local
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
