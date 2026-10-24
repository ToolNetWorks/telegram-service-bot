#!/usr/bin/env python3
"""Live end-to-end check against Turso using a mocked provider/Telegram.

Creates a throw-away user, walks the real onboarding + Telegram Members
ordering flow, then removes every test row.  No real provider order is placed.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from bot import App, env_file
from test_flows import MockVietnamFB, StubTelegram

TEST_UID = 990000001


def cleanup(app):
    db = app.db
    db.conn.execute(
        "DELETE FROM provider_orders WHERE order_id IN (SELECT id FROM orders WHERE user_id=?)",
        (TEST_UID,))
    db.conn.execute("DELETE FROM ledger WHERE user_id=?", (TEST_UID,))
    db.conn.execute("DELETE FROM deposits WHERE user_id=?", (TEST_UID,))
    db.conn.execute("DELETE FROM tickets WHERE user_id=?", (TEST_UID,))
    db.conn.execute("DELETE FROM orders WHERE user_id=?", (TEST_UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (TEST_UID,))


def message(uid, text=None, **attrs):
    payload = {"from": {"id": uid, "first_name": "Turso", "username": "tursotest"},
               "chat": {"id": uid, "type": "private"}}
    if text is not None:
        payload["text"] = text
    payload.update(attrs)
    return payload


def callback(uid, data):
    return {"id": f"q{uid}{data}", "from": {"id": uid, "first_name": "Turso"},
            "message": {"chat": {"id": uid, "type": "private"}}, "data": data}


def main() -> int:
    env_file(str(ROOT / ".env"))
    if not os.getenv("TURSO_URL") or not os.getenv("TURSO_TOKEN"):
        print("SKIP: Turso chưa cấu hình")
        return 0
    app = App()
    if app.db.backend != "turso":
        print("FAIL: bot không dùng Turso")
        return 1
    app.api = StubTelegram()
    app.username = "test_bot"
    app.provider = MockVietnamFB()
    try:
        cleanup(app)
        print("stage: cleanup OK")
        app.handle_message(message(TEST_UID, "/start"))
        print("stage: /start OK")
        state, data = app.db.get_state(TEST_UID)
        assert state == "captcha", state
        app.handle_message(message(TEST_UID, str(data["a"] + data["b"])))
        assert app.db.get_user(TEST_UID)["verified_at"], "chưa xác minh"
        app.handle_callback(callback(TEST_UID, "lang:vi"))
        assert app.db.get_user(TEST_UID)["language"] == "vi"
        print("stage: onboarding OK")

        assert app.db.credit(TEST_UID, 50000)
        assert app.db.get_user(TEST_UID)["balance"] == 50000
        for action in ("tools", "tools:engagement", "engagement:telegram_members",
                       "tg_member_select:1720"):
            app.handle_callback(callback(TEST_UID, action))
        print("stage: menu OK")
        app.handle_message(message(TEST_UID, "https://t.me/turso_check_group"))
        app.handle_message(message(TEST_UID, "1000"))
        state, data = app.db.get_state(TEST_UID)
        assert state == "tg_member_confirm", state
        assert data["total"] == 40, data
        print("stage: quote OK")

        app.handle_callback(callback(TEST_UID, "tg_member_confirm_pay"))
        print("stage: provider order OK")
        user = app.db.get_user(TEST_UID)
        assert user["balance"] == 49960, user["balance"]
        orders = app.db.list_orders(TEST_UID)
        assert len(orders) == 1, orders
        assert orders[0]["status"] == "processing", orders[0]["status"]
        provider_order = app.db.get_provider_order(orders[0]["id"])
        assert provider_order is not None
        assert provider_order["provider_order_id"] == "test_order_1"
        assert provider_order["quantity"] == 1000

        app.handle_callback(callback(TEST_UID, "tg_member_confirm_pay"))
        assert len(app.db.list_orders(TEST_UID)) == 1, "double confirm tạo đơn trùng"
        assert app.db.get_user(TEST_UID)["balance"] == 49960
        ledger = app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE user_id=? AND kind='provider_payment'",
            (TEST_UID,))["c"]
        assert ledger == 1, ledger

        # A provider-order rollback must not keep a partial row or debit.
        before = app.db.get_user(TEST_UID)["balance"]
        try:
            with app.db.transaction():
                app.db.conn.execute(
                    "UPDATE users SET balance=balance-1000 WHERE user_id=?", (TEST_UID,))
                app.db.conn.execute(
                    "INSERT INTO orders(user_id,service_id,request_key,subject,evidence_kind,"
                    "evidence,amount,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (TEST_UID, 999999, "rollback-check", "x", "x", "x", 1000,
                     "processing", "2026-01-01", "2026-01-01"))
        except Exception:
            pass
        else:
            raise AssertionError("FK violation phải làm rollback")
        assert app.db.get_user(TEST_UID)["balance"] == before, "rollback ví thất bại"

        print("TURSO APP CHECK OK: onboarding, wallet, order, duplicate guard, rollback")
        return 0
    finally:
        try:
            cleanup(app)
        finally:
            app.db.close()


if __name__ == "__main__":
    sys.exit(main())
