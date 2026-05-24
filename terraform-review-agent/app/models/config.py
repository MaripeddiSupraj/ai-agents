from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

_BUNDLED_POLICY_DIR = str(Path(__file__).parent.parent / "policies")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Terraform Review Agent"
    app_version: str = "1.0.0"
    debug: bool = False

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.1
    openai_max_tokens: int = 4096

    github_token: str = ""
    github_repository: str = ""
    github_pr_number: int = 0
    github_webhook_secret: str = ""

    redis_url: str = "redis://localhost:6379/0"
    redis_ttl: int = 3600

    terraform_dir: str = "./terraform/sample"
    terraform_binary: str = "terraform"

    opa_binary: str = "opa"
    opa_policy_dir: str = _BUNDLED_POLICY_DIR

    infracost_binary: str = "infracost"
    infracost_api_key: str = ""

    gcp_project_id: str = ""
    gcp_region: str = "us-central1"
    gcp_credentials_json: str = ""

    log_level: str = "INFO"
    log_format: str = "json"

    max_retries: int = 3
    retry_delay: float = 1.0

    @property
    def is_github_configured(self) -> bool:
        return bool(self.github_token and self.github_repository)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
