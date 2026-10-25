"""Shared runtime singletons (easy to override in tests)."""
from __future__ import annotations

from app.providers import provider_registry
from app.services.catalog import CatalogService
from app.services.orders import OrderService

catalog_service = CatalogService(provider_registry)
order_service = OrderService(catalog_service, provider_registry)
