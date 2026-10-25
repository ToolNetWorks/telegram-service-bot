"""Pydantic v2 API schemas for the Engagement API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlatformRead(BaseModel):
    id: int
    slug: str
    name: str
    name_en: str = ""
    icon: str = ""
    sort_order: int = 0
    enabled: bool = True
    coming_soon: bool = False
    visible: bool = True

    model_config = ConfigDict(from_attributes=True)


class CategoryRead(BaseModel):
    id: int
    platform_id: int
    platform_slug: str
    slug: str
    name: str
    name_en: str = ""
    sort_order: int = 0
    enabled: bool = True
    coming_soon: bool = False
    service_type: str = "engagement"

    model_config = ConfigDict(from_attributes=True)


class ProviderServiceRead(BaseModel):
    id: int
    category_id: int
    category_slug: str
    platform_slug: str
    provider_id: str
    provider_service_id: str
    name: str
    min_quantity: int
    max_quantity: int
    # Provider cost in 1/1000 VND per 1000 units.  Never a sale price.
    rate_milli: int
    status: Literal["active", "inactive"] = "active"
    cost_source: Literal["provider", "configured"] = "provider"

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    service_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    link: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)


class OrderResult(BaseModel):
    success: bool
    # False means the provider outcome is unknown; Bot Core must reconcile.
    definitive: bool = True
    provider_order_id: str | None = None
    charge_milli: int | None = None
    status: str | None = None
    error: str | None = None
    reconciliation_required: bool = False


class OrderStatus(BaseModel):
    provider_order_id: str
    provider: str
    status: str
    completed_quantity: int | None = None
    charge_milli: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class HealthLiveResponse(BaseModel):
    status: Literal["alive"]
    timestamp: datetime


class HealthReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    timestamp: datetime
    catalog: Literal["loaded", "unavailable"]
    providers_configured: int
    providers_total: int


class HealthDependenciesResponse(BaseModel):
    timestamp: datetime
    status: Literal["healthy", "degraded", "unhealthy"]
    providers: dict[str, Literal["ok", "error", "not_configured"]]


class HealthResponse(BaseModel):
    """Backward-compatible aggregate health response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    timestamp: datetime
    providers: dict[str, Literal["ok", "error", "not_configured"]]


class ErrorResponse(BaseModel):
    detail: str
    correlation_id: str | None = None
    definitive: bool | None = None


class PlatformsResponse(BaseModel):
    platforms: list[PlatformRead]


class CategoriesResponse(BaseModel):
    categories: list[CategoryRead]


class ServicesResponse(BaseModel):
    services: list[ProviderServiceRead]
