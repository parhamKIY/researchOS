from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESEARCHOS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    redis_url: SecretStr
    session_secret: SecretStr
    public_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    health_timeout_seconds: int = Field(default=2, ge=1, le=10)
    session_lifetime_hours: int = Field(default=12, ge=1, le=168)
    storage_root: Path = Path("storage")
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_infrastructure(self) -> "Settings":
        database = urlsplit(self.database_url.get_secret_value())
        redis = urlsplit(self.redis_url.get_secret_value())
        if database.scheme != "postgresql+psycopg" or not database.hostname or not database.path:
            raise ValueError("A PostgreSQL psycopg database URL is required")
        if redis.scheme not in {"redis", "rediss"} or not redis.hostname:
            raise ValueError("A Redis connection URL is required")
        if len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        origin = self.public_origin
        if (
            origin.path != "/"
            or origin.query
            or origin.fragment
            or origin.username
            or origin.password
        ):
            raise ValueError("Public origin must contain only scheme, host, and optional port")
        if origin.scheme != "https":
            if self.environment == "production" or origin.host not in {
                "localhost",
                "127.0.0.1",
                "[::1]",
            }:
                raise ValueError("HTTP is allowed only for local non-production development")
        return self
