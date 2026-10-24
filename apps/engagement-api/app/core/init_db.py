"""Database initialization for Engagement API."""
from __future__ import annotations

from app.core.database import db


SCHEMA_SQL = """
-- Engagement platforms
CREATE TABLE IF NOT EXISTS engagement_platforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    name_en TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    icon TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Engagement categories
CREATE TABLE IF NOT EXISTS engagement_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER NOT NULL REFERENCES engagement_platforms(id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    name_en TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    provider_category_id TEXT NOT NULL DEFAULT '',
    service_type TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform_id, slug)
);

-- Engagement provider services
CREATE TABLE IF NOT EXISTS engagement_provider_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES engagement_categories(id),
    provider_id TEXT NOT NULL DEFAULT 'vietnamfb',
    provider_service_id TEXT NOT NULL,
    name TEXT NOT NULL,
    min_quantity INTEGER NOT NULL DEFAULT 1,
    max_quantity INTEGER NOT NULL DEFAULT 1000000,
    rate_milli INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider_id, provider_service_id)
);

-- Provider orders (for tracking)
CREATE TABLE IF NOT EXISTS provider_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT NOT NULL,
    provider_service_id TEXT NOT NULL,
    provider_order_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    link TEXT NOT NULL,
    unit_price_milli INTEGER NOT NULL,
    charge_milli INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform ON engagement_categories(platform_id);
CREATE INDEX IF NOT EXISTS idx_engagement_provider_services_category ON engagement_provider_services(category_id);
CREATE INDEX IF NOT EXISTS idx_provider_orders_provider ON provider_orders(provider_name, provider_order_id);
CREATE INDEX IF NOT EXISTS idx_provider_orders_idempotency ON provider_orders(idempotency_key);
"""

ENGAGEMENT_PLATFORMS = [
    ("telegram", "Telegram", "Telegram", 1, 1, "📱"),
    ("youtube", "YouTube", "YouTube", 0, 2, "📺"),
    ("twitter", "Twitter (X)", "Twitter (X)", 0, 3, "🐦"),
    ("facebook", "Facebook", "Facebook", 0, 4, "📘"),
    ("instagram", "Instagram", "Instagram", 0, 5, "📷"),
    ("shopee", "Shopee", "Shopee", 0, 6, "🛍️"),
]

ENGAGEMENT_CATEGORIES = [
    (1, "members", "Member Telegram", "Member Telegram", 1, 1, "18", "member"),
    (1, "views", "View Telegram", "View Telegram", 0, 2, "", "view"),
]

# These will be synced from VietnamFB API
ENGAGEMENT_PROVIDER_SERVICES = [
    (1, "vietnamfb", "1720", "Telegram Members HQ", 10, 1000000, 40686, "active"),
    (1, "vietnamfb", "1510", "Telegram Members PLUS", 10, 1000000, 47664, "active"),
    (1, "vietnamfb", "1694", "Telegram Premium Members", 1, 500000, 142330, "active"),
]


def init_database() -> None:
    """Initialize database schema and seed data."""
    with db.transaction():
        # Execute schema
        db.executescript(SCHEMA_SQL)

        # Seed engagement platforms
        for slug, name, name_en, enabled, sort_order, icon in ENGAGEMENT_PLATFORMS:
            db.execute(
                """INSERT OR IGNORE INTO engagement_platforms(slug, name, name_en, enabled, sort_order, icon)
                   VALUES (?,?,?,?,?,?)""",
                (slug, name, name_en, enabled, sort_order, icon),
            )

        # Seed engagement categories
        for platform_id, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type in ENGAGEMENT_CATEGORIES:
            db.execute(
                """INSERT OR IGNORE INTO engagement_categories(
                       platform_id, slug, name, name_en, enabled, sort_order,
                       provider_category_id, service_type
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (platform_id, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type),
            )

        # Seed engagement provider services
        for cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status in ENGAGEMENT_PROVIDER_SERVICES:
            db.execute(
                """INSERT OR IGNORE INTO engagement_provider_services(
                       category_id, provider_id, provider_service_id, name,
                       min_quantity, max_quantity, rate_milli, status
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status),
            )


if __name__ == "__main__":
    init_database()
    print("Database initialized")