"""Configuration for Engagement API."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field
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

    # Internal authentication
    internal_token: str = Field(..., alias="ENGAGEMENT_INTERNAL_TOKEN")

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")
    database_token: str = Field(default="", alias="DATABASE_TOKEN")

    # Provider APIs
    vietnamfb_api_key: str = Field(..., alias="VIETNAMFB_API_KEY")
    vietnamfb_base_url: str = Field(default="https://vietnamfb.com", alias="VIETNAMFB_BASE_URL")

    # Security
    request_timeout: int = 30
    max_retries: int = 3
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Logging
    log_level: str = "INFO"


settings = Settings()

# Load .env file if exists
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