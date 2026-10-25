"""VietnamFB SMM panel provider.

All VietnamFB-specific knowledge (endpoint shape, credentials, service IDs,
cost prices, error classification) is isolated here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import (
    Provider,
    ProviderError,
    ProviderOrderData,
    ProviderServiceData,
)

LOG = logging.getLogger("engagement.provider.vietnamfb")


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except Exception:
        return Decimal(default)


def _milli(value: Decimal) -> int:
    return int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))


class VietnamFBProvider(Provider):
    """Async VietnamFB client using the standard SMM panel API format."""

    name = "vietnamfb"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        request_timeout: float | None = None,
        connect_timeout: float | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.vietnamfb_api_key).strip()
        self.base_url = (base_url or settings.vietnamfb_base_url).rstrip("/")
        self.request_timeout = request_timeout or settings.request_timeout
        self.connect_timeout = connect_timeout or settings.connect_timeout
        self.cache_ttl = cache_ttl if cache_ttl is not None else settings.provider_cache_ttl
        self._client: httpx.AsyncClient | None = None
        self._services_cache: list[ProviderServiceData] | None = None
        self._cache_time = 0.0
        self._cache_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.request_timeout,
                    connect=self.connect_timeout,
                ),
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(
        self,
        action: str,
        *,
        retries: int = 0,
        **params: Any,
    ) -> Any:
        if not self.configured:
            raise ProviderError(
                "VietnamFB provider is not configured",
                definitive=True,
                status_code=503,
            )

        payload = {"key": self.api_key, "action": action, **params}
        url = f"{self.base_url}/api/v2"
        attempts = max(0, retries) + 1
        last_error: ProviderError | None = None

        for attempt in range(attempts):
            try:
                response = await self._http().post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    f"VietnamFB {action} timed out",
                    definitive=False,
                )
                LOG.warning("VietnamFB timeout action=%s attempt=%s", action, attempt + 1)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                raise last_error from exc
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    f"VietnamFB {action} transport error",
                    definitive=False,
                )
                LOG.warning("VietnamFB transport error action=%s attempt=%s", action, attempt + 1)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                raise last_error from exc

            if response.status_code >= 500:
                last_error = ProviderError(
                    f"VietnamFB {action} HTTP {response.status_code}",
                    definitive=False,
                    status_code=response.status_code,
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                raise last_error

            if response.status_code >= 400:
                detail = response.text[:200]
                # 408/425 are ambiguous: the provider may still have processed
                # the request.  All other 4xx responses are definitive.
                definitive = response.status_code not in {408, 425}
                raise ProviderError(
                    f"VietnamFB {action} HTTP {response.status_code}: {detail}",
                    definitive=definitive,
                    status_code=response.status_code,
                )

            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProviderError(
                    f"VietnamFB {action} returned invalid JSON",
                    definitive=False,
                    status_code=response.status_code,
                ) from exc

            if isinstance(data, dict) and data.get("error"):
                raise ProviderError(
                    f"VietnamFB {action}: {data['error']}",
                    definitive=True,
                )
            return data

        raise last_error or ProviderError(f"VietnamFB {action} failed", definitive=False)

    async def get_services(self, force_refresh: bool = False) -> list[ProviderServiceData]:
        if (
            not force_refresh
            and self._services_cache is not None
            and (time.monotonic() - self._cache_time) < self.cache_ttl
        ):
            return list(self._services_cache)

        async with self._cache_lock:
            if (
                not force_refresh
                and self._services_cache is not None
                and (time.monotonic() - self._cache_time) < self.cache_ttl
            ):
                return list(self._services_cache)

            data = await self._post("services", retries=settings.max_retries)
            items = data if isinstance(data, list) else data.get("services", [])
            services: list[ProviderServiceData] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                try:
                    service_id = str(item.get("service", "")).strip()
                    if not service_id:
                        continue
                    services.append(
                        ProviderServiceData(
                            service_id=service_id,
                            name=str(item.get("name", "")).strip(),
                            rate_per_1000=_decimal(item.get("rate")),
                            min_quantity=int(item.get("min", 1)),
                            max_quantity=int(item.get("max", 1_000_000)),
                            category_id=str(item.get("category", "")),
                            category_name=str(item.get("category_name", "")),
                            raw=item,
                        )
                    )
                except (TypeError, ValueError) as exc:
                    LOG.warning("Skipping malformed provider service: %s", exc)

            self._services_cache = services
            self._cache_time = time.monotonic()
            return list(services)

    async def create_order(self, service_id: str, quantity: int, link: str) -> ProviderOrderData:
        # Never retry POST /add: a timeout may still have created the order.
        data = await self._post(
            "add",
            retries=0,
            service=service_id,
            quantity=quantity,
            link=link,
        )
        if not isinstance(data, dict):
            raise ProviderError("VietnamFB add returned an invalid payload", definitive=False)

        order_id = str(data.get("order", "")).strip()
        if not order_id:
            # Missing order id without an explicit provider error means the
            # outcome is unknown; Bot Core must reconcile.
            raise ProviderError(
                "VietnamFB add did not return an order id",
                definitive=False,
            )

        return ProviderOrderData(
            order_id=order_id,
            charge=_decimal(data.get("charge")) if data.get("charge") is not None else None,
            status=str(data.get("status", "processing") or "processing"),
            raw=data,
        )

    async def get_order_status(self, provider_order_id: str) -> dict[str, Any]:
        data = await self._post(
            "status",
            retries=settings.max_retries,
            order=provider_order_id,
        )
        if not isinstance(data, dict):
            raise ProviderError("VietnamFB status returned an invalid payload", definitive=False)
        return {
            "provider_order_id": str(data.get("order", provider_order_id)),
            "status": str(data.get("status", "unknown")),
            "charge": _decimal(data.get("charge")) if data.get("charge") is not None else None,
            "start_count": data.get("start_count"),
            "remains": data.get("remains"),
            "currency": data.get("currency", "VND"),
        }

    async def get_balance(self) -> Decimal:
        data = await self._post("balance", retries=settings.max_retries)
        if not isinstance(data, dict):
            raise ProviderError("VietnamFB balance returned an invalid payload", definitive=False)
        return _decimal(data.get("balance")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def provider_service_to_read(service: ProviderServiceData) -> dict[str, Any]:
    """Small helper used by tests and the catalog service."""
    return {
        "provider_service_id": service.service_id,
        "name": service.name,
        "rate_milli": _milli(service.rate_per_1000),
        "min_quantity": service.min_quantity,
        "max_quantity": service.max_quantity,
    }
