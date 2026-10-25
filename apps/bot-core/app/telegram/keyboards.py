"""Inline keyboard builders for Bot Core.

Keyboard builders only render data returned by the Engagement API.  They do not
contain platform, category, service or provider price lists.
"""
from __future__ import annotations

from typing import Any


def keyboard(*rows: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """Build an inline keyboard markup."""
    return {
        "inline_keyboard": [
            [{"text": title, "callback_data": data} for title, data in row]
            for row in rows
        ]
    }


def build_home_keyboard(t) -> dict[str, Any]:
    return keyboard(
        ((t("wallet"), "wallet"),),
        ((t("tools"), "tools"),),
        ((t("support"), "support"), (t("referral"), "referral")),
        ((t("faq"), "faq"), (t("changes"), "changelog")),
        ((t("orders"), "orders"), (t("language"), "language")),
    )


def build_tools_keyboard(t) -> dict[str, Any]:
    return keyboard(
        ((t("report"), "tools:report"), (t("engagement"), "tools:engagement")),
        ((t("tool_buy"), "tools:buy"), (t("tool_sub"), "tools:sub")),
        ((t("tool_back_main"), "home"),),
    )


def _platform_label(t, platform: dict) -> str:
    slug = platform.get("slug", "")
    name = t(f"engagement_{slug}") if t(f"engagement_{slug}") != f"engagement_{slug}" else platform.get("name", slug)
    icon = platform.get("icon", "")
    label = f"{icon} {name}".strip()
    if not platform.get("enabled", True) or platform.get("coming_soon", False):
        label = f"{label} {t('engagement_coming_soon')}"
    return label


def build_engagement_platforms_keyboard(t, platforms: list[dict]) -> dict[str, Any]:
    """Build the platform grid in two columns, including Coming Soon items."""
    visible = [item for item in platforms if item.get("visible", True)]
    rows: list[tuple[tuple[str, str], ...]] = []
    for index in range(0, len(visible), 2):
        row: list[tuple[str, str]] = []
        for platform in visible[index:index + 2]:
            slug = platform.get("slug", "")
            callback = (
                f"engagement:platform:{slug}"
                if platform.get("enabled", True) and not platform.get("coming_soon", False)
                else f"engagement:coming_soon:{slug}"
            )
            row.append((_platform_label(t, platform), callback))
        rows.append(tuple(row))

    rows.append(((t("back_tools"), "tools"),))
    return keyboard(*rows)


def _category_label(t, category: dict) -> str:
    slug = category.get("slug", "")
    name = category.get("name", slug)
    if category.get("platform_slug") == "telegram":
        if slug == "members":
            name = t("telegram_members")
        elif slug == "views":
            name = t("telegram_views")
    if not category.get("enabled", True) or category.get("coming_soon", False):
        name = f"{name} {t('engagement_coming_soon')}"
    return name


def build_engagement_categories_keyboard(t, categories: list[dict]) -> dict[str, Any]:
    """Build the category grid.  Disabled categories stay visible as Coming Soon."""
    rows: list[tuple[tuple[str, str], ...]] = []
    for index in range(0, len(categories), 2):
        row: list[tuple[str, str]] = []
        for category in categories[index:index + 2]:
            row.append((_category_label(t, category), f"engagement:category:{category['id']}"))
        rows.append(tuple(row))

    rows.append(((t("back_engagement"), "tools:engagement"),))
    return keyboard(*rows)


def sale_price_per_1000(rate_milli: int, markup_percent: int) -> int:
    """Convert provider cost (milli-VND per 1000) to the Bot Core sale price."""
    return max(0, int(rate_milli) * (100 + max(0, int(markup_percent))) // 100)


def build_service_packages_keyboard(
    t,
    services: list[dict],
    *,
    platform_slug: str,
    category_slug: str,
    markup_percent: int,
    platform_name: str = "",
) -> dict[str, Any]:
    """Build package buttons from API service data.

    Telegram Member keeps the historical ``tg_member_select:<id>`` callback so
    old messages continue to work.  Other services use the generic callback.
    """
    rows: list[tuple[tuple[str, str], ...]] = []
    for index in range(0, len(services), 2):
        row: list[tuple[str, str]] = []
        for service in services[index:index + 2]:
            price = sale_price_per_1000(service.get("rate_milli", 0), markup_percent)
            label = f"{service.get('name', 'Service')} · {price:,} VNĐ/1K"
            if platform_slug == "telegram" and category_slug == "members":
                callback = f"tg_member_select:{service['id']}"
            else:
                callback = f"engagement:service:{service['id']}"
            row.append((label, callback))
        rows.append(tuple(row))

    if platform_slug == "telegram":
        back_label = t("back_telegram")
    else:
        back_label = t("back_to_platform", platform=platform_name or platform_slug)
    rows.append(((back_label, f"engagement:platform:{platform_slug}"),))
    return keyboard(*rows)


def build_cancel_keyboard(t, back_action: str) -> dict[str, Any]:
    return keyboard(((t("cancel"), back_action),))


def build_confirm_keyboard(t, confirm_action: str, cancel_action: str) -> dict[str, Any]:
    return keyboard(((t("confirm_pay"), confirm_action), (t("cancel"), cancel_action)))


def build_back_keyboard(t, back_label: str, back_action: str) -> dict[str, Any]:
    return keyboard(((back_label, back_action),))
