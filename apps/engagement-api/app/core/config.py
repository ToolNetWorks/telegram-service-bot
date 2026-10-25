"""Configuration for the stateless Engagement API.

The Engagement API owns provider integration and the service catalog.  It does
**not** own financial data and must not receive a Turso token.  Durable order
and idempotency state belongs to Bot Core (see docs/engagement-api-contract.md).
"""
from __future__ import annotations

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
    environment: str = "production"
    host: str = "0.0.0.0"
    port: int = 8000

    # Internal authentication (required)
    internal_token: str = Field(..., alias="ENGAGEMENT_INTERNAL_TOKEN")

    # Provider APIs (required in production)
    vietnamfb_api_key: str = Field(default="", alias="VIETNAMFB_API_KEY")
    vietnamfb_base_url: str = Field(
        default="https://vietnamfb.com",
        alias="VIETNAMFB_BASE_URL",
    )

    # Provider transport
    request_timeout: float = 20.0
    connect_timeout: float = 5.0
    max_retries: int = 2
    provider_cache_ttl: int = 300

    # Security
    rate_limit_requests: int = 120
    rate_limit_window: int = 60

    # Logging
    log_level: str = "INFO"

    @field_validator("internal_token")
    @classmethod
    def validate_internal_token(cls, value: str) -> str:
        token = (value or "").strip()
        if not token:
            raise ValueError("ENGAGEMENT_INTERNAL_TOKEN must be set")
        return token

    @field_validator("vietnamfb_api_key")
    @classmethod
    def normalize_provider_key(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return (value or "production").strip().lower()

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    @property
    def provider_configured(self) -> bool:
        return bool(self.vietnamfb_api_key)


settings = Settings()

# Fail fast in production: without a provider key the API must not pretend to
# sell services.  Local/test environments may use a mock provider.
if settings.is_production and not settings.provider_configured:
    raise RuntimeError("VIETNAMFB_API_KEY must be set in production")
