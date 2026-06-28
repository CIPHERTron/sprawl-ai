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


worker_settings = WorkerSettings()
