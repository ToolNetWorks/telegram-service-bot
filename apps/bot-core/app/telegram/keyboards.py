"""Inline keyboard builders for Bot Core."""
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
    """Build main menu keyboard."""
    return keyboard(
        ((t("wallet"), "wallet"),),
        ((t("tools"), "tools"),),
        ((t("support"), "support"), (t("referral"), "referral")),
        ((t("faq"), "faq"), (t("changes"), "changelog")),
        ((t("orders"), "orders"), (t("language"), "language")),
    )


def build_tools_keyboard(t) -> dict[str, Any]:
    """Build Tool Access menu keyboard."""
    return keyboard(
        ((t("report"), "tools:report"), (t("engagement"), "tools:engagement")),
        ((t("tool_buy"), "tools:buy"), (t("tool_sub"), "tools:sub")),
        ((t("tool_back_main"), "home"),),
    )


def build_engagement_platforms_keyboard(t, platforms: list[dict]) -> dict[str, Any]:
    """Build engagement platforms grid (2 columns)."""
    rows = []
    for i in range(0, len(platforms), 2):
        row = []
        p1 = platforms[i]
        slug1 = p1.get("slug", "")
        if p1.get("enabled", True):
            label1 = f"{p1.get('icon', '')} {t(f'engagement_{slug1}')}"
            row.append((label1, f"engagement:platform:{slug1}"))
        else:
            label1 = f"{p1.get('icon', '')} {t(f'engagement_{slug1}')} {t('engagement_coming_soon')}"
            row.append((label1, f"engagement:coming_soon:{slug1}"))

        if i + 1 < len(platforms):
            p2 = platforms[i + 1]
            slug2 = p2.get("slug", "")
            if p2.get("enabled", True):
                label2 = f"{p2.get('icon', '')} {t(f'engagement_{slug2}')}"
                row.append((label2, f"engagement:platform:{slug2}"))
            else:
                label2 = f"{p2.get('icon', '')} {t(f'engagement_{slug2}')} {t('engagement_coming_soon')}"
                row.append((label2, f"engagement:coming_soon:{slug2}"))
        rows.append(tuple(row))

    rows.append(((t("back_tools"), "tools"),))
    return keyboard(*rows)


def build_engagement_categories_keyboard(t, categories: list[dict]) -> dict[str, Any]:
    """Build engagement categories grid (2 columns)."""
    rows = []
    for i in range(0, len(categories), 2):
        row = []
        c1 = categories[i]
        label1 = _get_category_label(t, c1)
        row.append((label1, f"engagement:category:{c1['id']}"))

        if i + 1 < len(categories):
            c2 = categories[i + 1]
            label2 = _get_category_label(t, c2)
            row.append((label2, f"engagement:category:{c2['id']}"))
        rows.append(tuple(row))

    rows.append(((t("back_engagement"), "tools:engagement"),))
    return keyboard(*rows)


def _get_category_label(t, category: dict) -> str:
    """Get localized label for a category."""
    slug = category.get("slug", "")
    if slug == "members":
        return t("telegram_members")
    if slug == "views":
        return t("telegram_views")
    return category.get("name", slug)


def build_member_packages_keyboard(t, packages: list[dict]) -> dict[str, Any]:
    """Build member packages keyboard (2 columns)."""
    rows = []
    for i in range(0, len(packages), 2):
        if i + 1 < len(packages):
            rows.append((
                (packages[i]["button_text"], f"tg_member_select:{packages[i]['service_id']}"),
                (packages[i + 1]["button_text"], f"tg_member_select:{packages[i + 1]['service_id']}"),
            ))
        else:
            rows.append(((packages[i]["button_text"], f"tg_member_select:{packages[i]['service_id']}"),))

    rows.append(((t("back_telegram"), "engagement:platform:telegram"),))
    return keyboard(*rows)


def build_cancel_keyboard(t, back_action: str) -> dict[str, Any]:
    """Build a simple cancel keyboard."""
    return keyboard(((t("cancel"), back_action),))


def build_confirm_keyboard(t, confirm_action: str, cancel_action: str) -> dict[str, Any]:
    """Build confirm/cancel keyboard."""
    return keyboard(
        ((t("confirm_pay"), confirm_action), (t("cancel"), cancel_action))
    )


def build_back_keyboard(t, back_label: str, back_action: str) -> dict[str, Any]:
    """Build a simple back button keyboard."""
    return keyboard(((back_label, back_action),))