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
        self.db.ensure_user(101, "customer", "Customer")
        self.db.ensure_user(102, "friend", "Friend", referral=101)

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
