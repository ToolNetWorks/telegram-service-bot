"""Bot Core UI, catalog and order-safety tests (mocked Engagement API)."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from unittest.mock import patch

from app.clients.engagement import (
    Category,
    EngagementAPIError,
    EngagementClient,
    OrderRequest,
    OrderResult,
    Platform,
    ProviderService,
)
from app.core.config import BotConfig
from app.core.state import StateManager
from app.database.connection import Database
from app.database.migrations import init_database
from app.modules.admin.repository import SettingsRepository
from app.modules.deposits.repository import DepositRepository
from app.modules.engagement.repository import EngagementRepository
from app.modules.orders.repository import OrderRepository
from app.modules.orders.services_repository import ServicesRepository
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.telegram.handlers import Handlers, Update

ADMIN_ID = 999
USER_ID = 111


class StubTelegram:
    username = "test_bot"

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.answered: list[str] = []

    def send_message(self, chat_id: int, text: str, markup: dict | None = None) -> dict:
        self.sent.append({"chat_id": chat_id, "text": text, "markup": markup})
        return {"message_id": len(self.sent)}

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.answered.append(callback_query_id)


class FakeEngagementClient:
    def __init__(self) -> None:
        self.fail = False
        self.order_result = OrderResult(
            success=True,
            provider_order_id="provider-1",
            charge_milli=40686,
            status="processing",
            definitive=True,
        )
        self.order_calls: list = []
        self.platforms = [
            Platform(1, "telegram", "Telegram", "Telegram", True, False, "📱", 1),
            Platform(2, "youtube", "YouTube", "YouTube", False, True, "📺", 2),
            Platform(3, "twitter", "Twitter (X)", "Twitter (X)", False, True, "🐦", 3),
            Platform(4, "facebook", "Facebook", "Facebook", False, True, "📘", 4),
            Platform(5, "instagram", "Instagram", "Instagram", False, True, "📷", 5),
            Platform(6, "shopee", "Shopee", "Shopee", False, True, "🛍️", 6),
        ]
        self.categories = {
            "telegram": [
                Category(101, 1, "telegram", "members", "Member Telegram", "Member Telegram", True, False, "member", 1),
                Category(102, 1, "telegram", "views", "View Telegram", "View Telegram", False, True, "view", 2),
            ],
        }
        self.services = {
            101: [
                ProviderService(1720, 101, "members", "telegram", "vietnamfb", "1720", "Telegram Members HQ", 10, 1_000_000, 40686),
                ProviderService(1510, 101, "members", "telegram", "vietnamfb", "1510", "Telegram Members PLUS", 10, 1_000_000, 47664),
                ProviderService(1694, 101, "members", "telegram", "vietnamfb", "1694", "Telegram Premium Members", 1, 500_000, 142330),
            ],
            102: [],
        }

    def _check(self) -> None:
        if self.fail:
            raise EngagementAPIError("catalog down", definitive=False)

    def list_platforms(self):
        self._check()
        return list(self.platforms)

    def list_categories(self, platform_slug: str):
        self._check()
        return list(self.categories.get(platform_slug, []))

    def get_category(self, category_id: int):
        self._check()
        for categories in self.categories.values():
            for category in categories:
                if category.id == category_id:
                    return category
        return None

    def list_services(self, category_id: int):
        self._check()
        return list(self.services.get(category_id, []))

    def get_service(self, service_id: int):
        self._check()
        for services in self.services.values():
            for service in services:
                if service.id == service_id:
                    return service
        return None

    def place_order(self, request):
        self._check()
        self.order_calls.append(request)
        return self.order_result


class BotCoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        config = BotConfig(
            bot_token="123:abc",
            admin_ids={ADMIN_ID},
            bot_name="Test",
            support_username="",
            db_path=os.path.join(self.tmp.name, "bot.sqlite3"),
            db_backend="sqlite",
            bank_name="Test Bank",
            bank_account="123",
            bank_owner="Test",
            engagement_api_url="http://engagement.invalid",
            engagement_api_token="test-token",
            log_level="INFO",
        )
        self.config = config
        self.db = Database(config)
        init_database(self.db)
        self.tg = StubTelegram()
        self.client = FakeEngagementClient()
        self.users = UserRepository(self.db)
        self.wallet = WalletRepository(self.db)
        self.deposits = DepositRepository(self.db)
        self.orders = OrderRepository(self.db)
        self.services = ServicesRepository(self.db)
        self.settings = SettingsRepository(self.db)
        self.state = StateManager(self.db)
        self.handlers = Handlers(
            config=config,
            db=self.db,
            tg_client=self.tg,
            user_repo=self.users,
            wallet_repo=self.wallet,
            deposit_repo=self.deposits,
            order_repo=self.orders,
            services_repo=self.services,
            engagement_repo=EngagementRepository(self.client),
            settings_repo=self.settings,
            state_manager=self.state,
            engagement_client=self.client,
        )
        self.users.ensure_user(USER_ID, "user", "User")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    # -- helpers ----------------------------------------------------

    def cb(self, data: str, uid: int = USER_ID) -> None:
        self.handlers.handle_update(
            Update(
                user_id=uid,
                username="user",
                display_name="User",
                message_id=1,
                text=None,
                callback_query_id="cb-1",
                callback_data=data,
                is_callback=True,
            )
        )

    def msg(self, text: str, uid: int = USER_ID) -> None:
        self.handlers.handle_update(
            Update(
                user_id=uid,
                username="user",
                display_name="User",
                message_id=1,
                text=text,
                callback_query_id=None,
                callback_data=None,
                is_callback=False,
            )
        )

    def last(self) -> dict:
        return self.tg.sent[-1]

    def buttons(self) -> list[str]:
        markup = self.last().get("markup") or {}
        return [
            button["callback_data"]
            for row in markup.get("inline_keyboard", [])
            for button in row
        ]

    def labels(self) -> list[str]:
        markup = self.last().get("markup") or {}
        return [
            button["text"]
            for row in markup.get("inline_keyboard", [])
            for button in row
        ]

    def balance(self, uid: int = USER_ID) -> int:
        return self.db.fetchone("SELECT balance FROM users WHERE user_id=?", (uid,))["balance"]

    def set_balance(self, amount: int, uid: int = USER_ID) -> None:
        self.db.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, uid))

    def prepare_confirm(self, quantity: int = 1000) -> None:
        self.set_balance(1_000_000)
        self.cb("tools:engagement")
        self.cb("engagement:platform:telegram")
        self.cb("engagement:category:101")
        self.cb("tg_member_select:1720")
        self.msg("https://t.me/testgroup")
        self.msg(str(quantity))

    # -- catalog / navigation --------------------------------------

    def test_turso_credentials_never_fall_back_to_sqlite(self) -> None:
        config = replace(self.config, db_backend=None)
        with patch.dict(
            os.environ,
            {"TURSO_URL": "libsql://example.invalid", "TURSO_TOKEN": "test-token"},
        ):
            with patch("app.database.connection.TURSO_AVAILABLE", False):
                with self.assertRaises(RuntimeError):
                    Database(config)

    def test_explicit_sqlite_ignores_turso_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"TURSO_URL": "libsql://example.invalid", "TURSO_TOKEN": "test-token"},
        ):
            db = Database(self.config)
            try:
                self.assertEqual(db.backend, "sqlite")
            finally:
                db.close()

    def test_duplicate_in_flight_response_is_ambiguous(self) -> None:
        client = EngagementClient(self.config)
        error = urllib.error.HTTPError(
            "http://engagement.invalid/v1/orders",
            409,
            "Conflict",
            None,
            io.BytesIO(b'{"detail": "Duplicate request is already in progress"}'),
        )
        with patch("app.clients.engagement.urllib.request.urlopen", side_effect=error):
            result = client.place_order(
                OrderRequest(
                    service_id=1720,
                    quantity=1000,
                    link="https://t.me/testgroup",
                    idempotency_key="duplicate-key",
                )
            )
        self.assertFalse(result.success)
        self.assertFalse(result.definitive)
        self.assertTrue(result.reconciliation_required)
        self.assertEqual(result.status, "pending_reconciliation")

    def test_malformed_order_response_is_ambiguous(self) -> None:
        client = EngagementClient(self.config)
        with patch.object(client, "_request", return_value={"unexpected": True}):
            result = client.place_order(
                OrderRequest(
                    service_id=1720,
                    quantity=1000,
                    link="https://t.me/testgroup",
                    idempotency_key="malformed-key",
                )
            )
        self.assertFalse(result.success)
        self.assertFalse(result.definitive)
        self.assertTrue(result.reconciliation_required)

    def test_platforms_come_from_api_and_include_coming_soon(self) -> None:
        self.cb("tools:engagement")
        self.assertIn("Engagement Services", self.last()["text"])
        buttons = self.buttons()
        self.assertIn("engagement:platform:telegram", buttons)
        self.assertIn("engagement:coming_soon:youtube", buttons)
        self.assertIn("engagement:coming_soon:twitter", buttons)
        self.assertIn("engagement:coming_soon:facebook", buttons)
        self.assertIn("engagement:coming_soon:instagram", buttons)
        self.assertIn("engagement:coming_soon:shopee", buttons)
        self.assertEqual(buttons[-1], "tools")
        self.assertIn("← Tool Access", self.labels())

    def test_telegram_categories_and_back(self) -> None:
        self.cb("engagement:platform:telegram")
        buttons = self.buttons()
        self.assertIn("engagement:category:101", buttons)
        self.assertIn("engagement:category:102", buttons)
        self.assertEqual(buttons[-1], "tools:engagement")
        self.assertIn("← Engagement Services", self.labels())
        self.assertIn("Member Telegram", self.last()["text"] + " Member Telegram")

    def test_member_packages_show_current_services_and_sale_price(self) -> None:
        self.cb("engagement:category:101")
        text = self.last()["text"]
        for expected in ("Telegram Members HQ", "Telegram Members PLUS", "Telegram Premium Members"):
            self.assertIn(expected, text)
        # Default markup is 100%: 40,686 -> 81,372 VND / 1,000.
        self.assertIn("81,372", text)
        buttons = self.buttons()
        self.assertIn("tg_member_select:1720", buttons)
        self.assertIn("tg_member_select:1510", buttons)
        self.assertIn("tg_member_select:1694", buttons)
        self.assertEqual(buttons[-1], "engagement:platform:telegram")

    def test_view_telegram_is_coming_soon(self) -> None:
        self.cb("engagement:category:102")
        self.assertIn("cập nhật", self.last()["text"].lower())
        self.assertEqual(self.buttons()[-1], "engagement:platform:telegram")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 0)

    def test_platform_coming_soon(self) -> None:
        self.cb("engagement:coming_soon:youtube")
        self.assertIn("cập nhật", self.last()["text"].lower())
        self.assertEqual(self.buttons()[-1], "tools:engagement")

    def test_legacy_callbacks_still_work(self) -> None:
        self.cb("engagement:telegram_members")
        self.assertIn("tg_member_select:1720", self.buttons())
        self.cb("tg_member_select:1720")
        self.assertEqual(self.state.get_state(USER_ID).name, "engagement_link")
        self.assertIn("Nhập link", self.last()["text"])

    def test_catalog_unavailable_does_not_break_menu(self) -> None:
        self.client.fail = True
        self.cb("tools:engagement")
        self.assertIn("tạm thời không khả dụng", self.last()["text"])
        self.assertEqual(self.buttons()[-1], "tools")

    # -- ordering ---------------------------------------------------

    def test_order_charges_once_and_uses_api(self) -> None:
        self.prepare_confirm()
        self.assertEqual(self.state.get_state(USER_ID).name, "engagement_confirm")
        self.assertIn("81,372", self.last()["text"])
        self.cb("engagement:confirm")

        self.assertEqual(len(self.client.order_calls), 1)
        self.assertEqual(self.client.order_calls[0].quantity, 1000)
        self.assertEqual(self.client.order_calls[0].idempotency_key.startswith("eng:"), True)
        self.assertEqual(self.balance(), 1_000_000 - 81_372)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM provider_orders")["c"], 1)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"],
            1,
        )
        provider_order = self.db.fetchone("SELECT * FROM provider_orders")
        self.assertEqual(provider_order["provider_service_id"], "1720")
        self.assertEqual(provider_order["api_price_per_1000_milli"], 40686)
        self.assertEqual(provider_order["unit_price_milli"], 81372)

    def test_double_confirm_does_not_double_charge_or_duplicate(self) -> None:
        self.prepare_confirm()
        self.cb("engagement:confirm")
        self.cb("engagement:confirm")
        self.assertEqual(len(self.client.order_calls), 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM provider_orders")["c"], 1)
        self.assertEqual(self.balance(), 1_000_000 - 81_372)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"],
            1,
        )

    def test_insufficient_balance_does_not_call_provider(self) -> None:
        self.prepare_confirm()
        self.set_balance(10)
        self.cb("engagement:confirm")
        self.assertEqual(len(self.client.order_calls), 0)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 0)
        self.assertIn("SỐ DƯ KHÔNG ĐỦ", self.last()["text"])

    def test_definitive_provider_error_refunds_exactly_once(self) -> None:
        self.client.order_result = OrderResult(
            success=False,
            error="Provider rejected service",
            definitive=True,
            status="failed",
        )
        self.prepare_confirm()
        self.cb("engagement:confirm")
        self.assertEqual(self.balance(), 1_000_000)
        order = self.db.fetchone("SELECT * FROM orders")
        self.assertEqual(order["status"], "rejected")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM provider_orders")["c"], 0)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"],
            1,
        )
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"],
            1,
        )
        self.assertTrue(
            any("CHƯA THỂ XÁC NHẬN" in item["text"] for item in self.tg.sent if item["chat_id"] == USER_ID)
        )

        # Replaying the callback must not refund twice.
        self.cb("engagement:confirm")
        self.assertEqual(self.balance(), 1_000_000)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"],
            1,
        )

    def test_ambiguous_provider_error_keeps_charge_for_reconciliation(self) -> None:
        self.client.order_result = OrderResult(
            success=False,
            error="Provider timeout",
            definitive=False,
            status="pending_reconciliation",
            reconciliation_required=True,
        )
        self.prepare_confirm()
        self.cb("engagement:confirm")
        self.assertEqual(self.balance(), 1_000_000 - 81_372)
        order = self.db.fetchone("SELECT * FROM orders")
        self.assertEqual(order["status"], "pending_reconciliation")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM provider_orders")["c"], 0)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"],
            0,
        )
        admin_texts = [item["text"] for item in self.tg.sent if item["chat_id"] == ADMIN_ID]
        self.assertTrue(any("đối soát" in text.lower() for text in admin_texts))

    def test_success_with_unknown_provider_order_id_is_held(self) -> None:
        self.client.order_result = OrderResult(
            success=False,
            error="Provider order ID missing in success response",
            definitive=False,
            status="pending_reconciliation",
            reconciliation_required=True,
        )
        self.prepare_confirm()
        self.cb("engagement:confirm")
        order = self.db.fetchone("SELECT * FROM orders")
        self.assertEqual(order["status"], "pending_reconciliation")
        self.assertEqual(self.balance(), 1_000_000 - 81_372)

    def test_legacy_confirm_callback_without_state(self) -> None:
        self.set_balance(1_000_000)
        self.cb("tg_member_confirm_pay:1720:https://t.me/testgroup:1000")
        self.assertEqual(len(self.client.order_calls), 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 1)
        self.assertEqual(self.balance(), 1_000_000 - 81_372)

    def test_legacy_confirm_replay_does_not_duplicate_order(self) -> None:
        self.set_balance(1_000_000)
        self.cb("tg_member_confirm_pay:1720:https://t.me/testgroup:1000")
        self.cb("tg_member_confirm_pay:1720:https://t.me/testgroup:1000")
        self.assertEqual(len(self.client.order_calls), 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 1)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM provider_orders")["c"], 1)
        self.assertEqual(self.balance(), 1_000_000 - 81_372)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"],
            1,
        )

    def test_begin_provider_order_is_idempotent(self) -> None:
        self.set_balance(1_000_000)
        service = self.services.get_or_create_engagement_service(
            name="Telegram Members HQ",
            provider_id="vietnamfb",
            provider_service_id="1720",
        )
        outcome, order = self.orders.begin_provider_order(
            user_id=USER_ID,
            service_id=service["id"],
            request_key="unit-duplicate-key",
            subject="https://t.me/testgroup",
            evidence="unit-test",
            amount=81_372,
        )
        self.assertEqual(outcome, "ok")
        self.assertIsNotNone(order)

        outcome2, order2 = self.orders.begin_provider_order(
            user_id=USER_ID,
            service_id=service["id"],
            request_key="unit-duplicate-key",
            subject="https://t.me/testgroup",
            evidence="unit-test",
            amount=81_372,
        )
        self.assertEqual(outcome2, "duplicate")
        self.assertEqual(order2["id"], order["id"])
        self.assertEqual(self.balance(), 1_000_000 - 81_372)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 1)
        self.assertEqual(
            self.db.fetchone("SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"],
            1,
        )

    def test_invalid_link_does_not_create_order(self) -> None:
        self.set_balance(1_000_000)
        self.cb("engagement:category:101")
        self.cb("tg_member_select:1720")
        self.msg("not-a-link")
        self.assertIn("LINK KHÔNG HỢP LỆ", self.last()["text"])
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"], 0)

    def test_quantity_bounds(self) -> None:
        self.set_balance(1_000_000)
        self.cb("engagement:category:101")
        self.cb("tg_member_select:1720")
        self.msg("https://t.me/testgroup")
        self.msg("1")
        self.assertIn("SỐ LƯỢNG KHÔNG HỢP LỆ", self.last()["text"])
        self.assertEqual(self.state.get_state(USER_ID).name, "engagement_qty")
        self.msg("1000001")
        self.assertIn("SỐ LƯỢNG KHÔNG HỢP LỆ", self.last()["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
