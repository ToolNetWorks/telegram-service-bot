import os
import sys
import tempfile
import unittest
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import Database
from bot import money, keyboard


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "test.sqlite3"))
        self._run_engagement_migration()
        self.db.ensure_user(101, "customer", "Customer")
        self.db.ensure_user(102, "friend", "Friend", referral=101)

    def _run_engagement_migration(self):
        """Run engagement migration on test database."""
        with self.db.transaction():
            # Platform table
            self.db.conn.execute("""
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
            self.db.conn.execute("""
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
            self.db.conn.execute("""
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
            self.db.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform 
                ON engagement_categories(platform_id)
            """)
            self.db.conn.execute("""
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
                self.db.conn.execute("""
                    INSERT OR IGNORE INTO engagement_platforms(slug, name, name_en, enabled, sort_order, icon)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (slug, name, name_en, enabled, sort_order, icon))
            # Insert Telegram categories
            telegram_platform = self.db.conn.execute(
                "SELECT id FROM engagement_platforms WHERE slug=?", ("telegram",)
            ).fetchone()
            if telegram_platform:
                platform_id = telegram_platform["id"]
                categories = [
                    (platform_id, "members", "Member Telegram", "Member Telegram", 1, 1, "18", "member"),
                    (platform_id, "views", "View Telegram", "View Telegram", 0, 2, "", "view"),
                ]
                for pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type in categories:
                    self.db.conn.execute("""
                        INSERT OR IGNORE INTO engagement_categories(
                            platform_id, slug, name, name_en, enabled, sort_order, 
                            provider_category_id, service_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type))
                # Insert default provider services for Telegram Members
                members_category = self.db.conn.execute(
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
                        self.db.conn.execute("""
                            INSERT OR IGNORE INTO engagement_provider_services(
                                category_id, provider_id, provider_service_id, name, 
                                min_quantity, max_quantity, rate_milli, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_referral_unique_on_repeated_start(self):
        self.db.ensure_user(102, "friend", "Friend", referral=999)
        self.assertEqual(self.db.referrals(101), 1)
        self.assertEqual(self.db.get_user(102)["referred_by"], 101)
        self.db.ensure_user(103, "n", "N", referral=103)
        self.assertIsNone(self.db.get_user(103)["referred_by"])

    def test_quoted_order_and_idempotent_payment(self):
        a = self.db.create_order(101, 1, "example.org content", "text", "evidence", "nonce1")
        self.assertEqual(a["status"], "awaiting_quote")
        self.assertEqual(self.db.create_order(101, 1, "different", "text", "evidence", "nonce1")["id"], a["id"])
        self.assertEqual(self.db.pay_order(a["id"], 101), "not_payable")
        self.assertIsNotNone(self.db.quote_order(a["id"], 500000))
        self.assertEqual(self.db.pay_order(a["id"], 102), "missing")
        self.assertEqual(self.db.pay_order(a["id"], 101), "insufficient")
        self.assertTrue(self.db.credit(101, 500000))
        self.assertEqual(self.db.pay_order(a["id"], 101), "paid")
        self.assertEqual(self.db.pay_order(a["id"], 101), "already_paid")
        self.assertEqual(self.db.get_user(101)["balance"], 0)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM ledger WHERE kind='order_payment'")["c"], 1)

    def test_reject_refund_once(self):
        self.db.set_price(2, 90000)
        order = self.db.create_order(101, 2, "violation.example/post", "photo", "fileid", "nonce2")
        self.assertEqual(order["status"], "awaiting_payment")
        self.db.credit(101, 100000)
        self.assertEqual(self.db.pay_order(order["id"], 101), "paid")
        self.assertEqual(self.db.get_user(101)["balance"], 10000)
        self.assertIsNone(self.db.set_order_status(order["id"], "completed"))
        self.assertIsNotNone(self.db.reject_order(order["id"]))
        self.assertIsNone(self.db.reject_order(order["id"]))
        self.assertEqual(self.db.get_user(101)["balance"], 100000)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 1)

    def test_deposit_manual_approval_once(self):
        dep = self.db.create_deposit(101, 200000)
        self.assertEqual(dep["status"], "waiting_proof")
        self.assertIsNone(self.db.deposit_action(dep["id"], True))
        self.assertIsNone(self.db.submit_proof(dep["id"], 102, "text", "fake"))
        self.assertIsNotNone(self.db.submit_proof(dep["id"], 101, "text", "bank trace"))
        self.assertIsNotNone(self.db.deposit_action(dep["id"], True))
        self.assertIsNone(self.db.deposit_action(dep["id"], True))
        self.assertEqual(self.db.get_user(101)["balance"], 200000)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM ledger WHERE kind='deposit'")["c"], 1)

    def test_unpaid_order_does_not_refund(self):
        order = self.db.create_order(101, 1, "Reported URL example.org", "text", "proof", "nonce3")
        self.assertIsNotNone(self.db.reject_order(order["id"]))
        self.assertEqual(self.db.get_user(101)["balance"], 0)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 0)

    def test_schema_upgrade_preserves_existing_wallet_and_price(self):
        path = os.path.join(self.tmp.name, "legacy.sqlite3")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '', balance INTEGER NOT NULL DEFAULT 0,
                referred_by INTEGER, state TEXT NOT NULL DEFAULT '',
                state_data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE services (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO users(user_id,balance,created_at) VALUES (789,350000,'2026-10-01');
            INSERT INTO services(id,title,description,price) VALUES
                (1,'Rà soát vi phạm TikTok','Old description',123456);
        """)
        conn.close()
        migrated = Database(path)
        self.assertEqual(migrated.get_user(789)["balance"], 350000)
        self.assertEqual(migrated.get_user(789)["verified_at"], "")
        self.assertEqual(migrated.get_service(1)["price"], 123456)
        self.assertEqual(migrated.get_service(1)["platform"], "tiktok")
        self.assertEqual(len(migrated.list_services()), 7)
        migrated.close()

    def test_claim_state_is_one_shot(self):
        self.db.set_state(101, "confirm", nonce="abc")
        self.assertTrue(self.db.claim_state(101, "confirm"))
        self.assertFalse(self.db.claim_state(101, "confirm"))
        state, data = self.db.get_state(101)
        self.assertEqual(state, "")
        self.assertEqual(data, {})

    def test_begin_provider_order_atomic_and_idempotent(self):
        self.assertTrue(self.db.credit(101, 100000))
        tool_id = self.db.get_service_by_title("Tool Access")["id"]
        outcome, order = self.db.begin_provider_order(
            101, tool_id, "tgprov:nonce1", "vietnamfb:1720", "link=https://t.me/x;qty=1000", 40000)
        self.assertEqual(outcome, "ok")
        self.assertEqual(self.db.get_user(101)["balance"], 60000)
        self.assertEqual(order["status"], "processing")
        self.assertEqual(order["paid"], 1)
        self.assertEqual(self.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"], 1)

        outcome2, order2 = self.db.begin_provider_order(
            101, tool_id, "tgprov:nonce1", "vietnamfb:1720", "link=https://t.me/x;qty=1000", 40000)
        self.assertEqual(outcome2, "duplicate")
        self.assertEqual(order2["id"], order["id"])
        self.assertEqual(self.db.get_user(101)["balance"], 60000)

        outcome3, _ = self.db.begin_provider_order(
            101, tool_id, "tgprov:nonce2", "vietnamfb:1720", "link=x;qty=1000", 90000)
        self.assertEqual(outcome3, "insufficient")
        self.assertEqual(self.db.get_user(101)["balance"], 60000)

    def test_attach_provider_order_is_idempotent(self):
        self.assertTrue(self.db.credit(101, 100000))
        tool_id = self.db.get_service_by_title("Tool Access")["id"]
        _, order = self.db.begin_provider_order(
            101, tool_id, "tgprov:nonce3", "vietnamfb:1720", "link=x;qty=10", 1000)
        first = self.db.attach_provider_order(
            order["id"], "vietnamfb", "1720", "provider-1", 10, "https://t.me/x",
            40686, 100, 20343, {"order": "provider-1"})
        second = self.db.attach_provider_order(
            order["id"], "vietnamfb", "1720", "provider-1", 10, "https://t.me/x",
            40686, 100, 20343, {"order": "provider-1"})
        self.assertEqual(first, second)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM provider_orders")["c"], 1)

    def test_service_catalog_and_caps(self):
        self.assertEqual(len(self.db.list_services()), 7)
        self.assertEqual(len(self.db.list_services("youtube")), 1)
        self.assertIsNone(self.db.create_deposit(101, 9999))
        self.assertFalse(self.db.set_price(1, -1))
        self.assertEqual(self.db.referrals(102), 0)
        self.assertEqual(money(1500000), "1.500.000 ₫")
        self.assertEqual(keyboard((("Back", "home"),))["inline_keyboard"][0][0]["callback_data"], "home")


if __name__ == "__main__":
    unittest.main()
