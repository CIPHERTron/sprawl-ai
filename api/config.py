"""
Central settings for the API service — reads from environment / .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database (asyncpg for both app and Alembic)
    database_url: str = "postgresql+asyncpg://sprawl:changeme@postgres:5432/sprawl"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Vault
    vault_addr: str = "http://vault:8200"
    vault_role_id: str = ""
    vault_secret_id: str = ""

    # Auth
    jwt_secret: str = "changeme-replace-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Demo
    demo_session_ttl_seconds: int = 3600
    demo_rate_limit_per_ip: int = 10


settings = Settings()
