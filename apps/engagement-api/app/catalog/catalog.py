"""Canonical, code-owned catalog metadata for engagement services.

Platforms and categories are presentation-independent metadata.  Provider
service IDs and cost prices are owned by the provider integration layer; the
definitions below are the allow-list that maps real provider services into
categories.  They are **not** Telegram UI data and contain no sale prices.

Bot Core receives this data through /v1/platforms, /v1/platforms/{slug}/categories
and /v1/categories/{id}/services.  It applies its own markup before showing a
price to a customer.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformDefinition:
    id: int
    slug: str
    name: str
    name_en: str
    icon: str
    sort_order: int
    enabled: bool
    coming_soon: bool
    visible: bool = True


@dataclass(frozen=True)
class CategoryDefinition:
    id: int
    platform_id: int
    slug: str
    name: str
    name_en: str
    sort_order: int
    enabled: bool
    coming_soon: bool
    service_type: str = "engagement"


@dataclass(frozen=True)
class ServiceDefinition:
    """Allow-list entry mapping one real provider service to a category."""

    id: int
    category_id: int
    provider_id: str
    provider_service_id: str
    display_name: str
    min_quantity: int
    max_quantity: int
    # Cost price in 1/1000 VND per 1000 units, used only when the provider
    # cannot be reached.  It is never a customer-facing sale price.
    fallback_rate_milli: int
    status: str = "active"


PLATFORMS: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(1, "telegram", "Telegram", "Telegram", "📱", 1, True, False),
    PlatformDefinition(2, "youtube", "YouTube", "YouTube", "📺", 2, False, True),
    PlatformDefinition(3, "twitter", "Twitter (X)", "Twitter (X)", "🐦", 3, False, True),
    PlatformDefinition(4, "facebook", "Facebook", "Facebook", "📘", 4, False, True),
    PlatformDefinition(5, "instagram", "Instagram", "Instagram", "📷", 5, False, True),
    PlatformDefinition(6, "shopee", "Shopee", "Shopee", "🛍️", 6, False, True),
)

CATEGORIES: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(101, 1, "members", "Member Telegram", "Member Telegram", 1, True, False, "member"),
    CategoryDefinition(102, 1, "views", "View Telegram", "View Telegram", 2, False, True, "view"),
    # Future categories are intentionally visible to API clients but carry no
    # services until a real provider mapping is added.
    CategoryDefinition(201, 2, "views", "YouTube Views", "YouTube Views", 1, False, True, "view"),
    CategoryDefinition(202, 2, "likes", "YouTube Likes", "YouTube Likes", 2, False, True, "like"),
    CategoryDefinition(203, 2, "subscribers", "YouTube Subscribers", "YouTube Subscribers", 3, False, True, "subscriber"),
    CategoryDefinition(301, 3, "followers", "Twitter Followers", "Twitter Followers", 1, False, True, "follower"),
    CategoryDefinition(401, 4, "followers", "Facebook Followers", "Facebook Followers", 1, False, True, "follower"),
    CategoryDefinition(402, 4, "likes", "Facebook Likes", "Facebook Likes", 2, False, True, "like"),
    CategoryDefinition(403, 4, "views", "Facebook Views", "Facebook Views", 3, False, True, "view"),
    CategoryDefinition(501, 5, "followers", "Instagram Followers", "Instagram Followers", 1, False, True, "follower"),
    CategoryDefinition(502, 5, "likes", "Instagram Likes", "Instagram Likes", 2, False, True, "like"),
    CategoryDefinition(503, 5, "views", "Instagram Views", "Instagram Views", 3, False, True, "view"),
    CategoryDefinition(601, 6, "followers", "Shopee Followers", "Shopee Followers", 1, False, True, "follower"),
    CategoryDefinition(602, 6, "likes", "Shopee Likes", "Shopee Likes", 2, False, True, "like"),
)

SERVICES: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(1720, 101, "vietnamfb", "1720", "Telegram Members HQ", 10, 1_000_000, 40_686),
    ServiceDefinition(1510, 101, "vietnamfb", "1510", "Telegram Members PLUS", 10, 1_000_000, 47_664),
    ServiceDefinition(1694, 101, "vietnamfb", "1694", "Telegram Premium Members", 1, 500_000, 142_330),
)

PLATFORMS_BY_ID = {item.id: item for item in PLATFORMS}
PLATFORMS_BY_SLUG = {item.slug: item for item in PLATFORMS}
CATEGORIES_BY_ID = {item.id: item for item in CATEGORIES}
SERVICES_BY_ID = {item.id: item for item in SERVICES}


def categories_for_platform(platform_id: int) -> list[CategoryDefinition]:
    return sorted(
        (item for item in CATEGORIES if item.platform_id == platform_id),
        key=lambda item: (item.sort_order, item.id),
    )


def services_for_category(category_id: int) -> list[ServiceDefinition]:
    return [item for item in SERVICES if item.category_id == category_id]
