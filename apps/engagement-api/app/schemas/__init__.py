"""Pydantic schemas for Engagement API."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict


class PlatformBase(BaseModel):
    slug: str
    name: str
    name_en: str = ""
    enabled: bool = True
    sort_order: int = 0
    icon: str = ""


class PlatformCreate(PlatformBase):
    pass


class PlatformRead(PlatformBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryBase(BaseModel):
    slug: str
    name: str
    name_en: str = ""
    enabled: bool = True
    sort_order: int = 0
    provider_category_id: str = ""
    service_type: str = "member"


class CategoryCreate(CategoryBase):
    platform_id: int


class CategoryRead(CategoryBase):
    id: int
    platform_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderServiceBase(BaseModel):
    provider_id: str = "vietnamfb"
    provider_service_id: str
    name: str
    min_quantity: int = 1
    max_quantity: int = 1000000
    rate_milli: int = 0
    status: Literal["active", "inactive"] = "active"


class ProviderServiceCreate(ProviderServiceBase):
    category_id: int


class ProviderServiceRead(ProviderServiceBase):
    id: int
    category_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    service_id: int
    quantity: int = Field(gt=0)
    link: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)


class OrderResult(BaseModel):
    success: bool
    provider_order_id: Optional[str] = None
    charge_milli: Optional[int] = None
    status: Optional[str] = None
    error: Optional[str] = None


class OrderStatus(BaseModel):
    provider_order_id: str
    status: str
    completed_quantity: Optional[int] = None
    charge_milli: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    timestamp: datetime
    database: Literal["connected", "disconnected"]
    database_backend: str
    providers: dict[str, Literal["ok", "error"]]


class ErrorResponse(BaseModel):
    detail: str
    correlation_id: Optional[str] = None


class PlatformsResponse(BaseModel):
    platforms: List[PlatformRead]


class CategoriesResponse(BaseModel):
    categories: List[CategoryRead]


class ServicesResponse(BaseModel):
    services: List[ProviderServiceRead]