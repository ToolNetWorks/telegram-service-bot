-- ToolNet Database Migrations
-- Migration 001: Initial schema for Bot Core and Engagement API
-- Run this on both databases (Bot Core and Engagement API share some tables)

-- ============================================
-- USERS & AUTHENTICATION
-- ============================================

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

CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by);

-- ============================================
-- SERVICES CATALOG (Bot Core)
-- ============================================

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0 CHECK(price >= 0),
    platform TEXT NOT NULL DEFAULT 'other',
    enabled INTEGER NOT NULL DEFAULT 1
);

-- ============================================
-- ORDERS (Bot Core)
-- ============================================

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

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- ============================================
-- PROVIDER ORDERS (Engagement API)
-- ============================================

CREATE TABLE IF NOT EXISTS provider_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
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

CREATE INDEX IF NOT EXISTS idx_provider_orders_order ON provider_orders(order_id);
CREATE INDEX IF NOT EXISTS idx_provider_orders_provider ON provider_orders(provider_name, provider_order_id);

-- ============================================
-- DEPOSITS (Bot Core)
-- ============================================

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

CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, created_at);

-- ============================================
-- LEDGER (Bot Core - Audit Trail)
-- ============================================

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    delta INTEGER NOT NULL,
    kind TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, reference)
);

CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, created_at);

-- ============================================
-- SUPPORT TICKETS (Bot Core)
-- ============================================

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

-- ============================================
-- SETTINGS (Bot Core)
-- ============================================

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============================================
-- ENGAGEMENT PLATFORMS (Shared)
-- ============================================

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

-- ============================================
-- ENGAGEMENT CATEGORIES (Shared)
-- ============================================

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

CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform ON engagement_categories(platform_id);

-- ============================================
-- ENGAGEMENT PROVIDER SERVICES (Shared)
-- ============================================

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

CREATE INDEX IF NOT EXISTS idx_engagement_provider_services_category ON engagement_provider_services(category_id);