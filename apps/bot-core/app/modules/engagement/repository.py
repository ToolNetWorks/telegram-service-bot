"""Engagement catalog access for Bot Core.

The catalog is always fetched from the Engagement API.  Bot Core must never
query provider tables or hardcode platforms/categories/services.
"""
from __future__ import annotations

from dataclasses import asdict

from app.clients.engagement import EngagementClient


class EngagementRepository:
    """Read-only catalog facade over the Engagement API."""

    def __init__(self, client: EngagementClient):
        self.client = client

    def list_platforms(self) -> list[dict]:
        return [asdict(item) for item in self.client.list_platforms()]

    def get_platform_by_slug(self, slug: str) -> dict | None:
        for platform in self.client.list_platforms():
            if platform.slug == slug:
                return asdict(platform)
        return None

    def list_categories(self, platform_slug: str) -> list[dict]:
        return [asdict(item) for item in self.client.list_categories(platform_slug)]

    def get_category(self, category_id: int) -> dict | None:
        category = self.client.get_category(category_id)
        return asdict(category) if category else None

    def list_provider_services(self, category_id: int) -> list[dict]:
        return [asdict(item) for item in self.client.list_services(category_id)]

    def get_provider_service(self, service_id: int) -> dict | None:
        service = self.client.get_service(service_id)
        return asdict(service) if service else None
