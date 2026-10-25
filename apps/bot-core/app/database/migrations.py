"""Database schema initialization and migrations.

Bot Core owns users, wallets, orders, deposits, ledger, referrals and settings.
It intentionally does **not** own the engagement catalog or provider orders'
provider-side data; those belong to the Engagement API.  ``provider_orders``
here is Bot Core's durable record of an order that Bot Core paid for.
"""
from __future__ import annotations

from app.database.connection import Database

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0 CHECK(price >= 0),
    platform TEXT NOT NULL DEFAULT 'other',
    enabled INTEGER NOT NULL DEFAULT 1
);

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

CREATE TABLE IF NOT EXISTS provider_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    provider_name TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    delta INTEGER NOT NULL,
    kind TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, reference)
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_request_key ON orders(request_key);
CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_provider_orders_order ON provider_orders(order_id);
CREATE INDEX IF NOT EXISTS idx_provider_orders_provider ON provider_orders(provider_name, provider_order_id);
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


def init_database(db: Database) -> None:
    """Initialize schema and seed Bot Core's own data only."""
    db.executescript(SCHEMA_SQL)

    with db.transaction():
        for title, description, platform in CATALOG:
            db.execute(
                "INSERT OR IGNORE INTO services(title, description, platform) VALUES (?,?,?)",
                (title, description, platform),
            )
            db.execute("UPDATE services SET platform=? WHERE title=?", (platform, title))

        db.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES ('provider_markup_percent','100')"
        )
