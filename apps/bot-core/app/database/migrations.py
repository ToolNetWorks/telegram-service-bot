"""Database schema initialization and migrations."""
from __future__ import annotations

from app.database.connection import Database

SCHEMA_SQL = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    referred_by INTEGER REFERENCES users(user_id),
    state TEXT NOT NULL DEFAULT '',
    state_data TEXT NOT NULL DEFAULT '{}',
    verified_at TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Services catalog
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0 CHECK(price >= 0),
    platform TEXT NOT NULL DEFAULT 'other',
    enabled INTEGER NOT NULL DEFAULT 1
);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    request_key TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount >= 0),
    paid INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Provider orders (for engagement services)
CREATE TABLE IF NOT EXISTS provider_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    provider_name TEXT NOT NULL DEFAULT 'vietnamfb',
    provider_service_id TEXT NOT NULL,
    provider_order_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    link TEXT NOT NULL,
    unit_price_milli INTEGER NOT NULL,
    markup_percent INTEGER NOT NULL DEFAULT 0,
    api_price_per_1000_milli INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    api_response TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider_name, provider_order_id)
);

-- Deposits
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    amount INTEGER NOT NULL CHECK(amount >= 10000),
    status TEXT NOT NULL,
    proof_kind TEXT NOT NULL DEFAULT '',
    proof TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Ledger for audit trail
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    delta INTEGER NOT NULL,
    kind TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, reference)
);

-- Support tickets
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

-- Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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

-- Indexes
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_provider_orders_order ON provider_orders(order_id);
CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform ON engagement_categories(platform_id);
CREATE INDEX IF NOT EXISTS idx_engagement_provider_services_category ON engagement_provider_services(category_id);
"""

CATALOG = (
    ("Rà soát vi phạm TikTok", "Tiếp nhận bằng chứng về nội dung vi phạm để đánh giá và hỗ trợ báo cáo hợp lệ.", "tiktok"),
    ("Rà soát vi phạm Telegram", "Tiếp nhận bằng chứng về nội dung/nhóm vi phạm quy định Telegram.", "telegram"),
    ("Hỗ trợ khiếu nại", "Hỗ trợ chủ tài khoản chuẩn bị hồ sơ khiếu nại hoặc khôi phục quyền truy cập.", "other"),
    ("Tool Access", "Tiếp nhận nhu cầu thuê/mua quyền sử dụng phần mềm hợp pháp.", "tools"),
    ("Rà soát vi phạm YouTube", "Tiếp nhận đường dẫn YouTube và tài liệu chứng minh dấu hiệu vi phạm.", "youtube"),
    ("Rà soát vi phạm Facebook", "Tiếp nhận báo cáo chính sách có bằng chứng về nội dung Facebook.", "facebook"),
    ("Rà soát vi phạm Instagram", "Tiếp nhận báo cáo chính sách có bằng chứng về nội dung Instagram.", "instagram"),
)

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

ENGAGEMENT_PROVIDER_SERVICES = [
    (1, "vietnamfb", "1720", "Telegram Members HQ", 10, 1000000, 40686, "active"),
    (1, "vietnamfb", "1510", "Telegram Members PLUS", 10, 1000000, 47664, "active"),
    (1, "vietnamfb", "1694", "Telegram Premium Members", 1, 500000, 142330, "active"),
]


def init_database(db: Database) -> None:
    """Initialize database schema and seed data."""
    with db.transaction():
        # Execute schema
        db.executescript(SCHEMA_SQL)
        
        # Seed services catalog
        for title, desc, platform in CATALOG:
            db.execute(
                "INSERT OR IGNORE INTO services(title, description, platform) VALUES (?,?,?)",
                (title, desc, platform),
            )
            db.execute(
                "UPDATE services SET platform=? WHERE title=?", (platform, title)
            )
        
        # Default markup for provider orders
        db.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES ('provider_markup_percent','100')"
        )
        
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