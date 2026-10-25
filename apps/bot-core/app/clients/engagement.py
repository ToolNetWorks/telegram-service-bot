"""HTTP client for the internal Engagement API.

Bot Core uses this client for *all* engagement catalog data and provider order
calls.  It contains no provider-specific rules, service IDs or prices.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import BotConfig

LOG = logging.getLogger("botcore.engagement")


@dataclass
class Platform:
    id: int
    slug: str
    name: str
    name_en: str = ""
    enabled: bool = True
    coming_soon: bool = False
    icon: str = ""
    sort_order: int = 0
    visible: bool = True


@dataclass
class Category:
    id: int
    platform_id: int
    platform_slug: str
    slug: str
    name: str
    name_en: str = ""
    enabled: bool = True
    coming_soon: bool = False
    service_type: str = "engagement"
    sort_order: int = 0


@dataclass
class ProviderService:
    id: int
    category_id: int
    category_slug: str
    platform_slug: str
    provider_id: str
    provider_service_id: str
    name: str
    min_quantity: int
    max_quantity: int
    rate_milli: int
    status: str = "active"
    cost_source: str = "provider"


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
    definitive: bool = True


class EngagementAPIError(Exception):
    """Engagement API error with a safety classification."""

    def __init__(self, message: str, *, definitive: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.definitive = definitive
        self.status_code = status_code


class EngagementClient:
    """Client for calling the internal Engagement API."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.base_url = config.engagement_api_url.rstrip("/")
        self.token = config.engagement_api_token
        self.timeout = 35

    def _request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Internal-Token": self.token,
        }
        data = json.dumps(json_data, ensure_ascii=False).encode("utf-8") if json_data is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code}"
            # 409 means another request with the same idempotency key is still
            # in flight.  Its provider outcome is unknown, so it must never be
            # treated as a definitive rejection/refund.
            definitive = exc.code not in {408, 409, 425, 429} and exc.code < 500
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("detail", detail)
                if isinstance(detail, list):
                    detail = "; ".join(str(item) for item in detail)
            except (ValueError, OSError):
                pass
            raise EngagementAPIError(
                f"Engagement API {method} {path}: {detail}",
                definitive=definitive,
                status_code=exc.code,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise EngagementAPIError(
                f"Network error calling Engagement API: {exc}",
                definitive=False,
            ) from None

    def health_check(self) -> bool:
        try:
            result = self._request("GET", "/health/ready")
            return result.get("status") == "ready"
        except EngagementAPIError:
            return False

    def health_dependencies(self) -> dict | None:
        try:
            return self._request("GET", "/health/dependencies")
        except EngagementAPIError:
            return None

    def list_platforms(self) -> list[Platform]:
        result = self._request("GET", "/v1/platforms")
        return [Platform(**item) for item in result.get("platforms", [])]

    def list_categories(self, platform_slug: str) -> list[Category]:
        result = self._request("GET", f"/v1/platforms/{platform_slug}/categories")
        return [Category(**item) for item in result.get("categories", [])]

    def get_category(self, category_id: int) -> Category | None:
        result = self._request("GET", f"/v1/categories/{category_id}")
        return Category(**result) if result else None

    def list_services(self, category_id: int) -> list[ProviderService]:
        result = self._request("GET", f"/v1/categories/{category_id}/services")
        return [ProviderService(**item) for item in result.get("services", [])]

    def get_service(self, service_id: int) -> ProviderService | None:
        result = self._request("GET", f"/v1/services/{service_id}")
        return ProviderService(**result) if result else None

    def place_order(self, request: OrderRequest) -> OrderResult:
        payload = {
            "service_id": request.service_id,
            "quantity": request.quantity,
            "link": request.link,
            "idempotency_key": request.idempotency_key,
        }
        try:
            result = self._request("POST", "/v1/orders", payload)
        except EngagementAPIError as exc:
            # A transport/5xx failure is ambiguous: the provider may have
            # accepted the order.  A 4xx is a definitive rejection.
            return OrderResult(
                success=False,
                error=exc.message,
                definitive=exc.definitive,
                status=None if exc.definitive else "pending_reconciliation",
                reconciliation_required=not exc.definitive,
            )

        if "success" not in result:
            LOG.error("Engagement API returned a malformed order response: %s", result)
            return OrderResult(
                success=False,
                error="Malformed Engagement API order response",
                status="pending_reconciliation",
                definitive=False,
                reconciliation_required=True,
            )

        api_success = bool(result.get("success", False))
        provider_order_id = result.get("provider_order_id")
        charge_milli = result.get("charge_milli")
        status = result.get("status")
        error = result.get("error")
        # Missing classification is treated as ambiguous, never as a refund.
        definitive = bool(result.get("definitive", False))
        reconciliation = bool(result.get("reconciliation_required", False))

        if not api_success:
            LOG.warning("Engagement API order failed definitive=%s: %s", definitive, error)
            return OrderResult(
                success=False,
                error=error or "Provider rejected order",
                status=status,
                definitive=definitive,
                reconciliation_required=reconciliation or not definitive,
            )

        if not provider_order_id:
            LOG.error("Engagement API returned success=true without provider_order_id")
            return OrderResult(
                success=False,
                error="Provider order ID missing in success response",
                status="pending_reconciliation",
                definitive=False,
                reconciliation_required=True,
            )

        return OrderResult(
            success=True,
            provider_order_id=str(provider_order_id),
            charge_milli=charge_milli,
            status=status,
            definitive=definitive,
            reconciliation_required=reconciliation or status == "pending_reconciliation",
        )

    def get_order_status(self, provider_order_id: str, provider: str) -> dict | None:
        try:
            return self._request(
                "GET",
                f"/v1/orders/{provider_order_id}/status?provider={provider}",
            )
        except EngagementAPIError:
            return None
