"""Integration test: Bot Core client -> real Engagement API -> mock VietnamFB.

The Engagement API is started as a subprocess and the VietnamFB provider is
replaced by a local HTTP server.  No real provider request is made.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.clients.engagement import EngagementAPIError, EngagementClient, OrderRequest
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

TOKEN = "integration-internal-token"
ENGAGEMENT_API_DIR = Path(__file__).resolve().parents[2] / "engagement-api"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


class MockVietnamFBHandler(BaseHTTPRequestHandler):
    """Minimal SMM-panel API used only by this test."""

    server_version = "MockVietnamFB/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/v2":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        fields = {key: values[0] for key, values in payload.items()}
        self.server.requests.append(fields)  # type: ignore[attr-defined]

        action = fields.get("action", "")
        if action == "services":
            self._json(
                [
                    {"service": "1720", "name": "Telegram Members HQ", "rate": "40.686", "min": 10, "max": 1_000_000},
                    {"service": "1510", "name": "Telegram Members PLUS", "rate": "47.664", "min": 10, "max": 1_000_000},
                    {"service": "1694", "name": "Telegram Premium Members", "rate": "142.330", "min": 1, "max": 500_000},
                    {"service": "9999", "name": "Not in allow-list", "rate": "1.000", "min": 1, "max": 10},
                ]
            )
            return

        if action == "add":
            link = fields.get("link", "")
            if "reject" in link:
                self._json({"error": "Service unavailable"})
                return
            if "ambiguous" in link:
                self._json({"error": "provider exploded"}, status=500)
                return
            self._json({"order": 987654, "charge": "40686.00", "status": "processing"})
            return

        if action == "status":
            self._json(
                {
                    "order": fields.get("order", ""),
                    "status": "completed",
                    "charge": "40686.00",
                    "start_count": "0",
                    "remains": "0",
                    "currency": "VND",
                }
            )
            return

        if action == "balance":
            self._json({"balance": "1000000.00"})
            return

        self._json({"error": f"unknown action {action}"})

    def _json(self, body, status: int = 200) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class EngagementAPIIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), MockVietnamFBHandler)
        cls.provider.requests = []  # type: ignore[attr-defined]
        cls.provider_thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.provider_thread.start()

        cls.api_port = _free_port()
        cls.api_log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "ENVIRONMENT": "test",
                "ENGAGEMENT_INTERNAL_TOKEN": TOKEN,
                "VIETNAMFB_API_KEY": "integration-provider-key",
                "VIETNAMFB_BASE_URL": f"http://127.0.0.1:{cls.provider.server_address[1]}",
                "HOST": "127.0.0.1",
                "PORT": str(cls.api_port),
                "LOG_LEVEL": "WARNING",
                "REQUEST_TIMEOUT": "5",
                "CONNECT_TIMEOUT": "2",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        cls.api_process = subprocess.Popen(
            [sys.executable, "-m", "app.main"],
            cwd=str(ENGAGEMENT_API_DIR),
            env=env,
            stdout=cls.api_log,
            stderr=subprocess.STDOUT,
        )
        cls._wait_for_api()

        cls.config = BotConfig(
            bot_token="123:abc",
            admin_ids={1},
            bot_name="Test",
            support_username="",
            db_path=os.path.join(tempfile.gettempdir(), "integration-unused.sqlite3"),
            db_backend="sqlite",
            bank_name="",
            bank_account="",
            bank_owner="",
            engagement_api_url=f"http://127.0.0.1:{cls.api_port}",
            engagement_api_token=TOKEN,
            log_level="INFO",
        )
        cls.client = EngagementClient(cls.config)

    @classmethod
    def _wait_for_api(cls) -> None:
        deadline = time.monotonic() + 30
        url = f"http://127.0.0.1:{cls.api_port}/health/live"
        while time.monotonic() < deadline:
            if cls.api_process.poll() is not None:
                cls.api_log.seek(0)
                output = cls.api_log.read()
                raise AssertionError(f"Engagement API exited during startup:\n{output}")
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.1)

        cls.api_log.seek(0)
        output = cls.api_log.read()
        raise AssertionError(f"Engagement API did not become ready:\n{output}")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.api_process.poll() is None:
            cls.api_process.terminate()
            try:
                cls.api_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.api_process.kill()
                cls.api_process.wait(timeout=10)
        cls.api_log.close()
        cls.provider.shutdown()
        cls.provider.server_close()
        cls.provider_thread.join(timeout=5)

    def _add_calls(self) -> list[dict]:
        return [item for item in self.provider.requests if item.get("action") == "add"]

    def test_health_and_authenticated_catalog(self) -> None:
        self.assertTrue(self.client.health_check())

        platforms = self.client.list_platforms()
        platform_slugs = [item.slug for item in platforms]
        # VietnamFB platforms + Telegram + Coming Soon platforms
        expected_platforms = {
            "facebook", "instagram", "threads", "tiktok",
            "telegram", "youtube", "twitter", "shopee"
        }
        self.assertEqual(set(platform_slugs), expected_platforms)
        telegram = next(item for item in platforms if item.slug == "telegram")
        self.assertTrue(telegram.enabled)
        youtube = next(item for item in platforms if item.slug == "youtube")
        self.assertTrue(youtube.coming_soon)

        categories = self.client.list_categories("telegram")
        self.assertEqual([item.id for item in categories], [101, 102])
        self.assertTrue(next(item for item in categories if item.id == 102).coming_soon)

        services = self.client.list_services(101)
        self.assertEqual([item.id for item in services], [1720, 1510, 1694])
        self.assertEqual(services[0].rate_milli, 40_686)
        self.assertEqual(services[0].cost_source, "provider")
        self.assertEqual(services[0].provider_service_id, "1720")

        # Provider IDs outside the allow-list must never leak into Bot Core.
        self.assertNotIn("9999", [item.provider_service_id for item in services])

    def test_order_success(self) -> None:
        result = self.client.place_order(
            OrderRequest(
                service_id=1720,
                quantity=1000,
                link="https://t.me/integration_success",
                idempotency_key="integration-success-1",
            )
        )
        self.assertTrue(result.success)
        self.assertTrue(result.definitive)
        self.assertEqual(result.provider_order_id, "987654")
        self.assertEqual(result.status, "processing")
        self.assertEqual(result.charge_milli, 40_686_000)

        status = self.client.get_order_status("987654", "vietnamfb")
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "completed")

    def test_definitive_provider_rejection_is_not_retried(self) -> None:
        before = len(self._add_calls())
        result = self.client.place_order(
            OrderRequest(
                service_id=1720,
                quantity=1000,
                link="https://t.me/reject_this",
                idempotency_key="integration-reject-1",
            )
        )
        self.assertFalse(result.success)
        self.assertTrue(result.definitive)
        self.assertFalse(result.reconciliation_required)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(self._add_calls()), before + 1)

    def test_ambiguous_provider_failure_requires_reconciliation(self) -> None:
        before = len(self._add_calls())
        result = self.client.place_order(
            OrderRequest(
                service_id=1720,
                quantity=1000,
                link="https://t.me/ambiguous_result",
                idempotency_key="integration-ambiguous-1",
            )
        )
        self.assertFalse(result.success)
        self.assertFalse(result.definitive)
        self.assertTrue(result.reconciliation_required)
        self.assertEqual(result.status, "pending_reconciliation")
        self.assertEqual(len(self._add_calls()), before + 1)

    def test_bot_core_handlers_end_to_end(self) -> None:
        """Full Bot Core UI -> real API -> mock provider order flow."""
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                self.config,
                db_path=os.path.join(tmp, "bot.sqlite3"),
                db_backend="sqlite",
            )
            db = Database(config)
            try:
                init_database(db)
                tg = StubTelegram()
                users = UserRepository(db)
                wallet = WalletRepository(db)
                orders = OrderRepository(db)
                client = EngagementClient(config)
                handlers = Handlers(
                    config=config,
                    db=db,
                    tg_client=tg,
                    user_repo=users,
                    wallet_repo=wallet,
                    deposit_repo=DepositRepository(db),
                    order_repo=orders,
                    services_repo=ServicesRepository(db),
                    engagement_repo=EngagementRepository(client),
                    settings_repo=SettingsRepository(db),
                    state_manager=StateManager(db),
                    engagement_client=client,
                )

                uid = 111
                users.ensure_user(uid, "user", "User")
                users.verify_user(uid)  # Verify user to skip CAPTCHA
                db.execute("UPDATE users SET balance=?", (1_000_000,))

                def callback(data: str) -> None:
                    handlers.handle_update(
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

                def message(text: str) -> None:
                    handlers.handle_update(
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

                before = len(self._add_calls())
                callback("tools:engagement")
                callback("engagement:platform:telegram")
                callback("engagement:category:101")
                callback("tg_member_select:1720")
                message("https://t.me/integration_e2e")
                message("1000")
                callback("engagement:confirm")

                self.assertEqual(len(self._add_calls()), before + 1)
                order = db.fetchone("SELECT * FROM orders")
                self.assertEqual(order["status"], "processing")
                self.assertEqual(order["amount"], 81_372)
                provider_order = db.fetchone("SELECT * FROM provider_orders")
                self.assertEqual(provider_order["provider_order_id"], "987654")
                self.assertEqual(provider_order["provider_service_id"], "1720")
                self.assertEqual(wallet.get_balance(uid), 1_000_000 - 81_372)
                self.assertTrue(
                    any(
                        "THÀNH CÔNG" in item["text"]
                        for item in tg.sent
                        if item["chat_id"] == uid
                    )
                )
            finally:
                db.close()

    def test_wrong_token_is_rejected(self) -> None:
        bad_client = EngagementClient(
            BotConfig(
                **{
                    **self.config.__dict__,
                    "engagement_api_token": "wrong-token",
                }
            )
        )
        with self.assertRaises(EngagementAPIError) as ctx:
            bad_client.list_platforms()
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertTrue(ctx.exception.definitive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
