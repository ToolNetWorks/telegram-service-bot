"""Configuration for Engagement API."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = "production"

    # Internal authentication (REQUIRED)
    internal_token: str = Field(..., alias="ENGAGEMENT_INTERNAL_TOKEN")

    # Database (REQUIRED for production)
    database_url: str = Field(default="", alias="DATABASE_URL")
    database_token: str = Field(default="", alias="DATABASE_TOKEN")

    # Provider APIs (REQUIRED for production)
    vietnamfb_api_key: str = Field(default="", alias="VIETNAMFB_API_KEY")
    vietnamfb_base_url: str = Field(default="https://vietnamfb.com", alias="VIETNAMFB_BASE_URL")

    # Security
    request_timeout: int = 30
    max_retries: int = 3
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Logging
    log_level: str = "INFO"

    @field_validator("internal_token")
    @classmethod
    def validate_internal_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("ENGAGEMENT_INTERNAL_TOKEN must be set")
        return v.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        # Allow empty for local SQLite testing, but warn
        return v.strip() if v else ""

    @field_validator("vietnamfb_api_key")
    @classmethod
    def validate_vietnamfb_api_key(cls, v: str) -> str:
        if not v or not v.strip():
            # Allow empty for local testing with mock provider
            return ""
        return v.strip()


settings = Settings()

# Fail-fast validation for production
if settings.environment == "production":
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be set in production")
    if not settings.vietnamfb_api_key:
        raise RuntimeError("VIETNAMFB_API_KEY must be set in production")

# Load .env file if exists (local development only)
env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.isupper() and name.replace("_", "").isalnum():
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))