#!/usr/bin/env python3
"""Migration script to add Engagement Services platform and category tables."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import Database, utcnow


def migrate(db: Database) -> None:
    """Add engagement platforms and service categories tables."""
    with db.transaction():
        # Platform table
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS engagement_platforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                name_en TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                icon TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Service Category table
        db.conn.execute("""
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
            )
        """)

        # Provider Service mapping table
        db.conn.execute("""
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
            )
        """)

        # Indexes
        db.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform 
            ON engagement_categories(platform_id)
        """)
        db.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_engagement_provider_services_category 
            ON engagement_provider_services(category_id)
        """)

        # Insert default platforms
        platforms = [
            ("telegram", "Telegram", "Telegram", 1, 1, "📱"),
            ("youtube", "YouTube", "YouTube", 0, 2, "📺"),
            ("twitter", "Twitter (X)", "Twitter (X)", 0, 3, "🐦"),
            ("facebook", "Facebook", "Facebook", 0, 4, "📘"),
            ("instagram", "Instagram", "Instagram", 0, 5, "📷"),
            ("shopee", "Shopee", "Shopee", 0, 6, "🛍️"),
        ]
        for slug, name, name_en, enabled, sort_order, icon in platforms:
            db.conn.execute("""
                INSERT OR IGNORE INTO engagement_platforms(slug, name, name_en, enabled, sort_order, icon)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (slug, name, name_en, enabled, sort_order, icon))

        # Insert Telegram categories
        telegram_platform = db.conn.execute(
            "SELECT id FROM engagement_platforms WHERE slug=?", ("telegram",)
        ).fetchone()
        if telegram_platform:
            platform_id = telegram_platform["id"]
            categories = [
                (platform_id, "members", "Member Telegram", "Member Telegram", 1, 1, "18", "member"),
                (platform_id, "views", "View Telegram", "View Telegram", 0, 2, "", "view"),
            ]
            for pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type in categories:
                db.conn.execute("""
                    INSERT OR IGNORE INTO engagement_categories(
                        platform_id, slug, name, name_en, enabled, sort_order, 
                        provider_category_id, service_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type))

        # Insert default provider services for Telegram Members (from TELEGRAM_MEMBER_PACKAGES)
        members_category = db.conn.execute(
            "SELECT id FROM engagement_categories WHERE platform_id=? AND slug=?", 
            (platform_id, "members")
        ).fetchone()
        if members_category:
            cat_id = members_category["id"]
            provider_services = [
                (cat_id, "vietnamfb", "1720", "Telegram Members HQ", 10, 1000000, 40686, "active"),
                (cat_id, "vietnamfb", "1510", "Telegram Members PLUS", 10, 1000000, 47664, "active"),
                (cat_id, "vietnamfb", "1694", "Telegram Premium Members", 1, 500000, 142330, "active"),
            ]
            for cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status in provider_services:
                db.conn.execute("""
                    INSERT OR IGNORE INTO engagement_provider_services(
                        category_id, provider_id, provider_service_id, name, 
                        min_quantity, max_quantity, rate_milli, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status))

        print("Migration completed successfully!")


def main():
    db_path = os.getenv("DB_PATH", "./data/bot.sqlite3")
    backend = os.getenv("DB_BACKEND", "").strip().lower() or None
    db = Database(db_path, backend=backend)
    try:
        migrate(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()