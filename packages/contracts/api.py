"""Shared API contracts between Bot Core and Engagement API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal
from decimal import Decimal


@dataclass
class Platform:
    """Engagement platform."""
    id: int
    slug: str
    name: str
    name_en: str
    enabled: bool
    sort_order: int
    icon: str
    created_at: datetime


@dataclass
class Category:
    """Engagement service category."""
    id: int
    platform_id: int
    slug: str
    name: str
    name_en: str
    enabled: bool
    sort_order: int
    provider_category_id: str
    service_type: str
    created_at: datetime


@dataclass
class ProviderService:
    """Provider service from SMM panel."""
    id: int
    category_id: int
    provider_id: str
    provider_service_id: str
    name: str
    min_quantity: int
    max_quantity: int
    rate_milli: int
    status: Literal["active", "inactive"]
    created_at: datetime


@dataclass
class OrderRequest:
    """Request to create an order."""
    service_id: int
    quantity: int
    link: str
    idempotency_key: str


@dataclass
class OrderResponse:
    """Response from order creation."""
    success: bool
    provider_order_id: Optional[str] = None
    charge_milli: Optional[int] = None
    status: Optional[str] = None
    error: Optional[str] = None


@dataclass
class OrderStatusResponse:
    """Order status from provider."""
    provider_order_id: str
    status: str
    completed_quantity: Optional[int] = None
    charge_milli: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# API Endpoints (for reference)
API_ENDPOINTS = {
    "health": "GET /health",
    "platforms": "GET /v1/platforms",
    "categories": "GET /v1/platforms/{platform_slug}/categories",
    "services": "GET /v1/categories/{category_id}/services",
    "service": "GET /v1/services/{service_id}",
    "create_order": "POST /v1/orders",
    "order_status": "GET /v1/orders/{provider_order_id}/status",
}

# Internal headers
INTERNAL_HEADERS = {
    "auth": "X-Internal-Token",
    "correlation_id": "X-Correlation-ID",
}

# Error codes
ERROR_CODES = {
    "UNAUTHORIZED": "Invalid internal token",
    "NOT_FOUND": "Resource not found",
    "VALIDATION_ERROR": "Invalid request data",
    "PROVIDER_ERROR": "Provider API error",
    "RATE_LIMITED": "Rate limit exceeded",
    "INTERNAL_ERROR": "Internal server error",
}