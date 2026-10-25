"""Order orchestration for provider calls.

Durable idempotency and wallet state are owned by Bot Core.  This service adds
a best-effort in-flight duplicate guard and, most importantly, classifies
provider failures so Bot Core never refunds an ambiguous order.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, ROUND_HALF_UP

from app.providers.base import ProviderError, ProviderRegistry
from app.schemas import OrderCreate, OrderResult, OrderStatus
from app.services.catalog import CatalogService

LOG = logging.getLogger("engagement.orders")


class ServiceNotFoundError(Exception):
    pass


class InvalidQuantityError(Exception):
    pass


class ProviderUnavailableError(Exception):
    pass


class DuplicateInFlightError(Exception):
    pass


def _milli(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))


class OrderService:
    def __init__(self, catalog_service: CatalogService, registry: ProviderRegistry) -> None:
        self.catalog = catalog_service
        self.registry = registry
        self._inflight: set[str] = set()
        self._lock = asyncio.Lock()

    async def _claim(self, key: str) -> None:
        async with self._lock:
            if key in self._inflight:
                raise DuplicateInFlightError("Duplicate request is already in progress")
            self._inflight.add(key)

    async def _release(self, key: str) -> None:
        async with self._lock:
            self._inflight.discard(key)

    async def create_order(self, order: OrderCreate) -> OrderResult:
        service = await self.catalog.get_service(order.service_id)
        if service is None:
            raise ServiceNotFoundError("Service not found or unavailable")

        if order.quantity < service.min_quantity or order.quantity > service.max_quantity:
            raise InvalidQuantityError(
                f"Quantity must be between {service.min_quantity} and {service.max_quantity}"
            )

        provider = self.registry.get(service.provider_id)
        if provider is None or not provider.configured:
            raise ProviderUnavailableError("Provider is not configured")

        await self._claim(order.idempotency_key)
        try:
            provider_order = await provider.create_order(
                service_id=service.provider_service_id,
                quantity=order.quantity,
                link=order.link,
            )
        except ProviderError as exc:
            LOG.warning(
                "Provider order failed idempotency_key=%s definitive=%s",
                order.idempotency_key,
                exc.definitive,
                extra={"provider": provider.name},
            )
            if exc.definitive:
                return OrderResult(
                    success=False,
                    definitive=True,
                    status="failed",
                    error=exc.message,
                )
            return OrderResult(
                success=False,
                definitive=False,
                status="pending_reconciliation",
                error=exc.message,
                reconciliation_required=True,
            )
        finally:
            await self._release(order.idempotency_key)

        return OrderResult(
            success=True,
            definitive=True,
            provider_order_id=provider_order.order_id,
            charge_milli=_milli(provider_order.charge),
            status=provider_order.status or "processing",
        )

    async def get_status(self, provider_order_id: str, provider_name: str) -> OrderStatus:
        provider = self.registry.get(provider_name)
        if provider is None or not provider.configured:
            raise ProviderUnavailableError("Provider is not configured")

        result = await provider.get_order_status(provider_order_id)
        return OrderStatus(
            provider_order_id=str(result.get("provider_order_id", provider_order_id)),
            provider=provider_name,
            status=str(result.get("status", "unknown")),
            completed_quantity=result.get("completed_quantity"),
            charge_milli=_milli(result.get("charge")),
            error_message=result.get("error"),
        )
