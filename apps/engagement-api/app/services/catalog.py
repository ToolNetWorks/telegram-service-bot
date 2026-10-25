"""Catalog service: joins code-owned metadata with live provider data."""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

from app.catalog import catalog
from app.providers.base import ProviderError, ProviderRegistry, ProviderServiceData
from app.schemas import CategoryRead, PlatformRead, ProviderServiceRead

LOG = logging.getLogger("engagement.catalog")


def _milli(value: Decimal) -> int:
    return int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))


class CatalogService:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def list_platforms(self) -> list[PlatformRead]:
        return [
            PlatformRead(
                id=item.id,
                slug=item.slug,
                name=item.name,
                name_en=item.name_en,
                icon=item.icon,
                emoji=item.emoji,
                sort_order=item.sort_order,
                enabled=item.enabled,
                coming_soon=item.coming_soon,
                visible=item.visible,
            )
            for item in catalog.PLATFORMS
            if item.visible
        ]

    def get_platform(self, slug: str) -> PlatformRead | None:
        item = catalog.PLATFORMS_BY_SLUG.get(slug)
        if item is None or not item.visible:
            return None
        return PlatformRead(
            id=item.id,
            slug=item.slug,
            name=item.name,
            name_en=item.name_en,
            icon=item.icon,
            emoji=item.emoji,
            sort_order=item.sort_order,
            enabled=item.enabled,
            coming_soon=item.coming_soon,
            visible=item.visible,
        )

    def list_categories(self, platform_slug: str) -> list[CategoryRead] | None:
        platform = catalog.PLATFORMS_BY_SLUG.get(platform_slug)
        if platform is None or not platform.visible:
            return None
        return [
            CategoryRead(
                id=item.id,
                platform_id=item.platform_id,
                platform_slug=platform.slug,
                slug=item.slug,
                name=item.name,
                name_en=item.name_en,
                sort_order=item.sort_order,
                enabled=item.enabled,
                coming_soon=item.coming_soon,
                service_type=item.service_type,
            )
            for item in catalog.categories_for_platform(platform.id)
        ]

    def get_category(self, category_id: int) -> CategoryRead | None:
        item = catalog.CATEGORIES_BY_ID.get(category_id)
        if item is None:
            return None
        platform = catalog.PLATFORMS_BY_ID.get(item.platform_id)
        if platform is None or not platform.visible:
            return None
        return CategoryRead(
            id=item.id,
            platform_id=item.platform_id,
            platform_slug=platform.slug,
            slug=item.slug,
            name=item.name,
            name_en=item.name_en,
            sort_order=item.sort_order,
            enabled=item.enabled,
            coming_soon=item.coming_soon,
            service_type=item.service_type,
        )

    async def list_services(self, category_id: int) -> list[ProviderServiceRead] | None:
        category = self.get_category(category_id)
        if category is None:
            return None
        if not category.enabled or category.coming_soon:
            return []

        definitions = catalog.services_for_category(category_id)
        if not definitions:
            return []

        provider_id = definitions[0].provider_id
        provider = self.registry.get(provider_id)
        if provider is None or not provider.configured:
            LOG.warning("Provider %s is not configured; hiding services", provider_id)
            return []

        remote_services: dict[str, ProviderServiceData] | None = None
        try:
            fetched = await provider.get_services()
            remote_services = {item.service_id: item for item in fetched}
        except ProviderError as exc:
            # Do not hide the whole menu during a transient provider outage;
            # expose the configured cost and mark its source explicitly.
            LOG.warning("Provider %s service sync failed: %s", provider_id, exc)

        result: list[ProviderServiceRead] = []
        for definition in definitions:
            remote = remote_services.get(definition.provider_service_id) if remote_services is not None else None
            if remote_services is not None and remote is None:
                # Provider answered successfully but no longer offers this ID.
                continue

            if remote is not None:
                name = remote.name or definition.name
                min_quantity = max(1, remote.min_quantity)
                max_quantity = max(min_quantity, remote.max_quantity)
                rate_milli = _milli(remote.rate_per_1000)
                cost_source = "provider"
            else:
                name = definition.name
                min_quantity = definition.min_quantity
                max_quantity = definition.max_quantity
                rate_milli = definition.rate_milli
                cost_source = "configured"

            result.append(
                ProviderServiceRead(
                    id=definition.id,
                    category_id=category.id,
                    category_slug=category.slug,
                    platform_slug=category.platform_slug,
                    provider_id=definition.provider_id,
                    provider_service_id=definition.provider_service_id,
                    name=name,
                    min_quantity=min_quantity,
                    max_quantity=max_quantity,
                    rate_milli=rate_milli,
                    status=definition.status,
                    cost_source=cost_source,
                )
            )
        return result

    async def get_service(self, service_id: int) -> ProviderServiceRead | None:
        definition = catalog.SERVICES_BY_ID.get(service_id)
        if definition is None:
            return None
        services = await self.list_services(definition.category_id)
        if not services:
            return None
        return next((item for item in services if item.id == service_id), None)
