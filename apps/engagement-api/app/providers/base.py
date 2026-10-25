"""Provider abstractions for the Engagement API."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


class ProviderError(Exception):
    """A provider error with an explicit safety classification.

    ``definitive=True`` means the provider rejected the request and no order
    was created.  ``definitive=False`` means the outcome is unknown (timeout,
    transport failure, 5xx); the caller must reconcile instead of refunding.
    """

    def __init__(
        self,
        message: str,
        *,
        definitive: bool = True,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.definitive = definitive
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderServiceData:
    service_id: str
    name: str
    rate_per_1000: Decimal
    min_quantity: int
    max_quantity: int
    category_id: str = ""
    category_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderOrderData:
    order_id: str
    charge: Decimal | None = None
    status: str = "processing"
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    """One module per provider.  No provider logic may live in Bot Core."""

    name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether credentials/base URL are present."""

    @abstractmethod
    async def get_services(self, force_refresh: bool = False) -> list[ProviderServiceData]:
        """Return the provider's current service list."""

    @abstractmethod
    async def create_order(self, service_id: str, quantity: int, link: str) -> ProviderOrderData:
        """Create a real provider order.  Never retried automatically."""

    @abstractmethod
    async def get_order_status(self, provider_order_id: str) -> dict[str, Any]:
        """Return the provider's current order status."""

    @abstractmethod
    async def get_balance(self) -> Decimal:
        """Return provider account balance for dependency health checks."""

    async def close(self) -> None:
        """Release network resources."""


class ProviderRegistry:
    """Name -> provider module registry."""

    def __init__(self, providers: dict[str, Provider] | None = None) -> None:
        self._providers = dict(providers or {})

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def names(self) -> list[str]:
        return sorted(self._providers)

    def all(self) -> list[Provider]:
        return [self._providers[name] for name in self.names()]

    async def close(self) -> None:
        for provider in self.all():
            await provider.close()
