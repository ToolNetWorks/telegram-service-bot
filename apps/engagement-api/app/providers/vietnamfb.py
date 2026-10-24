"""VietnamFB SMM Panel API Client for Engagement API."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from app.core.config import settings

LOG = logging.getLogger("engagement.providers.vietnamfb")


class VietnamFBError(Exception):
    """VietnamFB API error."""
    pass


@dataclass
class Service:
    service_id: str
    name: str
    category_id: str
    category_name: str
    platform_id: str
    platform_name: str
    price_per_1000: Decimal
    min_quantity: int
    max_quantity: int
    average_time: str
    type: str
    service_note: str
    refill: bool
    cancel: bool


@dataclass
class OrderResult:
    order_id: str
    charge: Optional[Decimal] = None
    start_count: Optional[int] = None
    remains: Optional[int] = None
    currency: str = "VND"


class VietnamFBAPI:
    """VietnamFB SMM Panel API Client."""

    def __init__(self, api_key: str = None, base_url: str = None, timeout: int = 30):
        self.api_key = api_key or settings.vietnamfb_api_key
        self.base_url = (base_url or settings.vietnamfb_base_url).rstrip("/")
        self.timeout = timeout
        self._services_cache: list[Service] | None = None
        self._cache_time = 0

    def _request(self, action: str, **params) -> dict:
        """Make API request to VietnamFB."""
        url = f"{self.base_url}/?mc=panel&site={action}&api_key={self.api_key}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", f"HTTP {exc.code}")
            except (ValueError, OSError):
                detail = f"HTTP {exc.code}"
            raise VietnamFBError(f"API {action}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VietnamFBError(f"Network error: {exc}") from None

    def get_services(self, force_refresh: bool = False) -> list[Service]:
        """Get all services from API with caching."""
        if not force_refresh and self._services_cache and (time.time() - self._cache_time) < 300:
            return self._services_cache

        data = self._request("services")
        services = []
        for item in data:
            try:
                services.append(Service(
                    service_id=str(item.get("service", "")),
                    name=item.get("name", ""),
                    category_id=str(item.get("category", "")),
                    category_name=item.get("category_name", ""),
                    platform_id=str(item.get("platform", "")),
                    platform_name=item.get("platform_name", ""),
                    price_per_1000=Decimal(str(item.get("rate", "0"))).quantize(Decimal("0.01"), ROUND_HALF_UP),
                    min_quantity=int(item.get("min", 1)),
                    max_quantity=int(item.get("max", 1000000)),
                    average_time=item.get("average_time", ""),
                    type=item.get("type", ""),
                    service_note=item.get("service_note", ""),
                    refill=bool(item.get("refill", False)),
                    cancel=bool(item.get("cancel", False)),
                ))
            except (ValueError, KeyError) as exc:
                LOG.warning("Skipping invalid service: %s", exc)

        self._services_cache = services
        self._cache_time = time.time()
        return services

    def create_order(self, service_id: str, quantity: int, link: str) -> OrderResult:
        """Create an order via VietnamFB API."""
        data = self._request(
            "add",
            service=service_id,
            quantity=quantity,
            link=link,
        )

        return OrderResult(
            order_id=str(data.get("order", "")),
            charge=Decimal(str(data.get("charge", "0"))) if data.get("charge") else None,
            start_count=int(data.get("start_count", 0)) if data.get("start_count") else None,
            remains=int(data.get("remains", 0)) if data.get("remains") else None,
            currency=data.get("currency", "VND"),
        )

    def get_order_status(self, order_id: str) -> dict:
        """Get order status from VietnamFB."""
        data = self._request("order_status", order=order_id)
        return {
            "order_id": str(data.get("order", "")),
            "status": data.get("status", "unknown"),
            "charge": Decimal(str(data.get("charge", "0"))) if data.get("charge") else None,
            "start_count": int(data.get("start_count", 0)) if data.get("start_count") else None,
            "remains": int(data.get("remains", 0)) if data.get("remains") else None,
            "currency": data.get("currency", "VND"),
        }

    def get_balance(self) -> Decimal:
        """Get account balance."""
        data = self._request("balance")
        return Decimal(str(data.get("balance", "0"))).quantize(Decimal("0.01"), ROUND_HALF_UP)


# Global instance
vietnamfb_client = VietnamFBAPI()