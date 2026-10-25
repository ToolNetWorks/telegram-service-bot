"""Engagement API client for Bot Core."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from app.core.config import BotConfig

LOG = logging.getLogger("botcore.engagement")


@dataclass
class Platform:
    id: int
    slug: str
    name: str
    name_en: str
    enabled: bool
    icon: str
    sort_order: int | None = None
    created_at: str | None = None


@dataclass
class Category:
    id: int
    platform_id: int
    slug: str
    name: str
    name_en: str
    enabled: bool
    provider_category_id: str
    service_type: str
    sort_order: int | None = None
    created_at: str | None = None


@dataclass
class ProviderService:
    id: int
    category_id: int
    provider_id: str
    provider_service_id: str
    name: str
    min_quantity: int
    max_quantity: int
    rate_milli: int
    status: str
    created_at: str | None = None


@dataclass
class OrderRequest:
    service_id: int
    quantity: int
    link: str
    idempotency_key: str


@dataclass
class OrderResult:
    success: bool
    provider_order_id: str | None = None
    charge_milli: int | None = None
    error: str | None = None
    status: str | None = None
    reconciliation_required: bool = False


class EngagementAPIError(Exception):
    """Engagement API error."""
    pass


class EngagementClient:
    """Client for calling the internal Engagement API."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.base_url = config.engagement_api_url.rstrip("/")
        self.token = config.engagement_api_token
        self.timeout = 30

    def _request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        """Make HTTP request to Engagement API."""
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json", "X-Internal-Token": self.token}

        data = json.dumps(json_data, ensure_ascii=False).encode("utf-8") if json_data else None

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", f"HTTP {exc.code}")
            except (ValueError, OSError):
                detail = f"HTTP {exc.code}"
            raise EngagementAPIError(f"Engagement API {method} {path}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EngagementAPIError(f"Network error calling Engagement API: {exc}") from None

    def health_check(self) -> bool:
        """Check if Engagement API is healthy (ready to serve)."""
        try:
            result = self._request("GET", "/health/ready")
            return result.get("status") == "ready"
        except EngagementAPIError:
            return False

    def health_dependencies(self) -> dict | None:
        """Get dependency health status."""
        try:
            return self._request("GET", "/health/dependencies")
        except EngagementAPIError:
            return None

    def list_platforms(self) -> list[Platform]:
        """Get all platforms."""
        result = self._request("GET", "/v1/platforms")
        return [Platform(**p) for p in result.get("platforms", [])]

    def list_categories(self, platform_slug: str) -> list[Category]:
        """Get categories for a platform."""
        result = self._request("GET", f"/v1/platforms/{platform_slug}/categories")
        return [Category(**c) for c in result.get("categories", [])]

    def list_services(self, category_id: int) -> list[ProviderService]:
        """Get provider services for a category."""
        result = self._request("GET", f"/v1/categories/{category_id}/services")
        return [ProviderService(**s) for s in result.get("services", [])]

    def get_service(self, service_id: int) -> ProviderService | None:
        """Get a single provider service."""
        result = self._request("GET", f"/v1/services/{service_id}")
        if result:
            return ProviderService(**result)
        return None

    def place_order(self, request: OrderRequest) -> OrderResult:
        """Place an order via Engagement API.
        
        Properly handles:
        - success=false responses (provider error)
        - HTTP 200 with missing provider_order_id
        - reconciliation_required flag
        - pending_reconciliation status
        """
        payload = {
            "service_id": request.service_id,
            "quantity": request.quantity,
            "link": request.link,
            "idempotency_key": request.idempotency_key,
        }
        try:
            result = self._request("POST", "/v1/orders", payload)
            
            # CRITICAL: Always check the actual 'success' field, not HTTP status
            api_success = result.get("success", False)
            provider_order_id = result.get("provider_order_id")
            charge_milli = result.get("charge_milli")
            status = result.get("status")
            error = result.get("error")
            reconciliation_required = result.get("reconciliation_required", False)
            
            if not api_success:
                # Provider returned success=false - this is a definitive failure
                LOG.warning("Engagement API order failed: %s", error)
                return OrderResult(
                    success=False,
                    error=error or "Provider rejected order",
                    status=status,
                )
            
            # API says success=true, but validate provider_order_id exists
            if not provider_order_id:
                LOG.error("Engagement API returned success=true but missing provider_order_id: %s", result)
                return OrderResult(
                    success=False,
                    error="Provider order ID missing in success response",
                    status=status,
                )
            
            # Determine if this is a confirmed order or needs reconciliation
            is_reconciliation = reconciliation_required or status == "pending_reconciliation"
            
            LOG.info("Order placed: provider_order_id=%s, status=%s, reconciliation=%s", 
                     provider_order_id, status, is_reconciliation)
            
            return OrderResult(
                success=True,
                provider_order_id=provider_order_id,
                charge_milli=charge_milli,
                status=status,
                reconciliation_required=is_reconciliation,
            )
        except EngagementAPIError as exc:
            LOG.error("Engagement API error placing order: %s", exc)
            return OrderResult(success=False, error=str(exc))

    def get_order_status(self, provider_order_id: str) -> dict | None:
        """Get order status from provider."""
        try:
            result = self._request("GET", f"/v1/orders/{provider_order_id}/status")
            return result
        except EngagementAPIError:
            return None