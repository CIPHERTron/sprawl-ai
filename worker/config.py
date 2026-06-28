"""
Worker service configuration — reads from environment / .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sprawl:changeme@postgres:5432/sprawl"
    redis_url: str = "redis://redis:6379/0"
    vault_addr: str = "http://vault:8200"
    vault_role_id: str = ""
    vault_secret_id: str = ""
    environment: str = "development"
    log_level: str = "INFO"
    demo_session_ttl_seconds: int = 3600

    # ── AWS / connector settings (M5) ──────────────────────────────────────────
    aws_role_arn: str = ""
    aws_external_id: str = ""
    github_token: str = ""

    # ── LLM (M5) ───────────────────────────────────────────────────────────────
    litellm_model: str = "ollama/llama3.2"
    ollama_base_url: str = "http://ollama:11434"
    litellm_api_key: str = ""

    # ── Langfuse observability (M5) ────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse-web:3000"

    @property
    def pg_dsn(self) -> str:
        """
        Plain psycopg3 connection string for LangGraph's AsyncPostgresSaver.
        Strips the '+asyncpg' SQLAlchemy driver prefix.
        """
        return self.database_url.replace("+asyncpg", "")


worker_settings = WorkerSettings()
