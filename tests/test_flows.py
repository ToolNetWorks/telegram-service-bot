import os
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot import App, TOOLS_GIF, WELCOME_GIF
from vietnamfb_api import Service, VietnamFBError


class StubTelegram:
    def __init__(self):
        self.calls = []

    def send(self, chat_id, text, markup=None):
        self.calls.append(("sendMessage", chat_id, text, markup))
        return {"message_id": len(self.calls)}

    def call(self, method, **params):
        self.calls.append((method, params))
        return True

    def send_media(self, chat_id, kind, file_id, caption, markup=None):
        method = {"photo": "sendPhoto", "animation": "sendAnimation"}[kind]
        return self.call(method, **{"chat_id": chat_id, kind: file_id,
                                    "caption": caption, "reply_markup": markup})

    def send_animation_file(self, chat_id, path, caption, markup=None):
        name = os.path.splitext(os.path.basename(path))[0]
        self.calls.append(("sendAnimationFile", chat_id, caption, markup))
        return {"animation": {"file_id": f"{name}-file-id"}}


class MockVietnamFB:
    """Mock VietnamFB API for testing."""
    def __init__(self):
        self.services = [
            Service(
                service_id="1720",
                name="Telegram Members HQ",
                category_id="18",
                category_name="Telegram Members",
                platform_id="2",
                platform_name="Telegram",
                price_per_1000=Decimal("20.343"),
                min_quantity=10,
                max_quantity=1000000,
                average_time="50-100k/Day",
                type="Default",
                service_note="Cancel/Refill Enabled | Refill: 7 Days",
                refill=True,
                cancel=True,
            ),
            Service(
                service_id="1510",
                name="Telegram Members",
                category_id="18",
                category_name="Telegram Members",
                platform_id="2",
                platform_name="Telegram",
                price_per_1000=Decimal("23.832"),
                min_quantity=10,
                max_quantity=1000000,
                average_time="30-50k/day",
                type="Default",
                service_note="Non Drop [+10% OverFlow] All types Links",
                refill=True,
                cancel=True,
            ),
            Service(
                service_id="1694",
                name="Telegram - Premium Members",
                category_id="18",
                category_name="Telegram Members",
                platform_id="2",
                platform_name="Telegram",
                price_per_1000=Decimal("71.165"),
                min_quantity=1,
                max_quantity=500000,
                average_time="10K/Days",
                type="Default",
                service_note="15-20 Days Non Drop | Instant - 10D Refill",
                refill=True,
                cancel=True,
            ),
        ]
        self.orders = {}
        self.balance = Decimal("0")

    def get_telegram_member_services(self):
        return self.services

    def get_service(self, service_id):
        for svc in self.services:
            if svc.service_id == service_id:
                return svc
        return None

    def get_services(self):
        return self.services

    def add_order(self, service_id, link, quantity, **kwargs):
        order_id = f"test_order_{len(self.orders) + 1}"
        self.orders[order_id] = {
            "service_id": service_id,
            "link": link,
            "quantity": quantity,
            "status": "processing",
        }
        return type('OrderResult', (), {
            "order_id": order_id,
            "charge": None,
            "start_count": 0,
            "remains": quantity,
            "status": "processing",
            "currency": "VND",
        })()

    def get_balance(self):
        return type('BalanceInfo', (), {"balance": self.balance, "currency": "VND"})()


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fake_env = {
            "BOT_TOKEN": "100000:dummy", "ADMIN_IDS": "999", "BOT_NAME": "Test",
            "DB_PATH": os.path.join(self.tmp.name, "bot.sqlite3"), "BANK_NAME": "Demo Bank",
            "BANK_ACCOUNT": "123456789", "BANK_OWNER": "Demo Owner",
            "VIETNAMFB_API_KEY": "test_key_12345",
            "VIETNAMFB_BASE_URL": "https://test.vietnamfb.com",
        }
        self.patch = patch.dict(os.environ, fake_env)
        self.patch.start()
        self.app = App()
        self.app.api = StubTelegram()
        self.app.username = "test_bot"
        # Run engagement migration for test database
        self._run_engagement_migration()
        # Mock the provider API
        self.mock_provider = MockVietnamFB()
        self.app.provider = self.mock_provider

    def _run_engagement_migration(self):
        """Run engagement migration on test database."""
        with self.app.db.transaction():
            # Platform table
            self.app.db.conn.execute("""
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
            self.app.db.conn.execute("""
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
            self.app.db.conn.execute("""
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
            self.app.db.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_engagement_categories_platform 
                ON engagement_categories(platform_id)
            """)
            self.app.db.conn.execute("""
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
                self.app.db.conn.execute("""
                    INSERT OR IGNORE INTO engagement_platforms(slug, name, name_en, enabled, sort_order, icon)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (slug, name, name_en, enabled, sort_order, icon))
            # Insert Telegram categories
            telegram_platform = self.app.db.conn.execute(
                "SELECT id FROM engagement_platforms WHERE slug=?", ("telegram",)
            ).fetchone()
            if telegram_platform:
                platform_id = telegram_platform["id"]
                categories = [
                    (platform_id, "members", "Member Telegram", "Member Telegram", 1, 1, "18", "member"),
                    (platform_id, "views", "View Telegram", "View Telegram", 0, 2, "", "view"),
                ]
                for pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type in categories:
                    self.app.db.conn.execute("""
                        INSERT OR IGNORE INTO engagement_categories(
                            platform_id, slug, name, name_en, enabled, sort_order, 
                            provider_category_id, service_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pid, slug, name, name_en, enabled, sort_order, provider_cat_id, svc_type))
                # Insert default provider services for Telegram Members
                members_category = self.app.db.conn.execute(
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
                        self.app.db.conn.execute("""
                            INSERT OR IGNORE INTO engagement_provider_services(
                                category_id, provider_id, provider_service_id, name, 
                                min_quantity, max_quantity, rate_milli, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (cat_id, provider_id, provider_svc_id, name, min_qty, max_qty, rate, status))

    def tearDown(self):
        self.app.db.close()
        self.patch.stop()
        self.tmp.cleanup()

    def msg(self, uid, text=None, **attrs):
        m = {"from": {"id": uid, "first_name": "Customer", "username": "user"},
             "chat": {"id": uid, "type": "private"}}
        if text is not None:
            m["text"] = text
        m.update(attrs)
        self.app.handle_message(m)

    def cb(self, uid, action):
        self.app.handle_callback({
            "id": f"q{uid}{action}", "from": {"id": uid, "first_name": "Customer"},
            "message": {"chat": {"id": uid, "type": "private"}}, "data": action,
        })

    def onboard(self, uid=111, language="vi"):
        self.msg(uid, "/start")
        state, data = self.app.db.get_state(uid)
        self.assertEqual(state, "captcha")
        self.msg(uid, str(data["a"] + data["b"]))
        self.assertTrue(self.app.db.get_user(uid)["verified_at"])
        self.cb(uid, f"lang:{language}")
        self.assertEqual(self.app.db.get_user(uid)["language"], language)

    def last_markup(self):
        for call in reversed(self.app.api.calls):
            if len(call) >= 4 and call[0] in ("sendMessage", "sendAnimationFile") and call[3]:
                return call[3]
            if call[0] in ("sendAnimation", "sendPhoto") and len(call) >= 2 and isinstance(call[1], dict):
                markup = call[1].get("reply_markup")
                if markup:
                    return markup
        raise AssertionError("no message with inline keyboard")

    def buttons(self):
        return [button["callback_data"]
                for row in self.last_markup()["inline_keyboard"] for button in row]

    def test_main_menu_excludes_report_and_tool_access_has_submenu(self):
        self.onboard()
        self.msg(111, "/start")
        self.assertNotIn("services", self.buttons())
        self.assertIn("tools", self.buttons())

        self.cb(111, "tools")
        self.assertEqual(self.buttons(), ["tools:report", "tools:engagement", "tools:buy", "tools:sub", "home"])

        self.cb(111, "tools:report")
        self.assertIn("platform:telegram", self.buttons())
        self.assertEqual(self.buttons()[-1], "tools")

        self.cb(111, "home")
        self.cb(111, "tools")
        self.cb(111, "tools:buy")
        tool_ids = [f"service:{s['id']}" for s in self.app.db.list_services("tools")]
        self.assertEqual(self.buttons(), tool_ids + ["tools"])

        self.cb(111, "tools:sub")
        self.assertIn("chưa có gói Tool Access", self.app.api.calls[-1][2])
        self.assertEqual(self.buttons(), ["tools:buy", "tools"])

    def test_engagement_services_displays_telegram_members(self):
        self.onboard()
        self.cb(111, "tools")
        self.app.api.calls.clear()
        self.cb(111, "tools:engagement")
        # Check platform grid - 6 platforms in 2 columns + back button
        buttons = self.buttons()
        self.assertIn("engagement:platform:telegram", buttons)
        self.assertIn("engagement:coming_soon:youtube", buttons)
        self.assertIn("engagement:coming_soon:twitter", buttons)
        self.assertIn("engagement:coming_soon:facebook", buttons)
        self.assertIn("engagement:coming_soon:instagram", buttons)
        self.assertIn("engagement:coming_soon:shopee", buttons)
        self.assertIn("tools", buttons)
        self.assertIn("Engagement Services", self.app.api.calls[-1][2])

        # Click on Telegram platform
        self.app.api.calls.clear()
        self.cb(111, "engagement:platform:telegram")
        buttons = self.buttons()
        # Should show categories: Member Telegram (enabled) + back button
        # View Telegram is disabled by default
        self.assertTrue(any(b.startswith("engagement:category:") for b in buttons))
        self.assertIn("tools:engagement", buttons)

        # Click on Member Telegram category
        self.app.api.calls.clear()
        members_cat_callback = [b for b in buttons if b.startswith("engagement:category:")][0]
        self.cb(111, members_cat_callback)
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(texts)
        text = texts[-1]
        for expected in ("Telegram Members HQ", "Telegram Members", "Telegram - Premium Members",
                         "40,686", "47,664", "142,330", "#1720", "#1510", "#1694"):
            self.assertIn(expected, text)
        # Check buttons - should have 3 service buttons in 2 columns + back button
        buttons = self.buttons()
        self.assertIn("tg_member_select:1720", buttons)
        self.assertIn("tg_member_select:1510", buttons)
        self.assertIn("tg_member_select:1694", buttons)
        self.assertIn("engagement:platform:telegram", buttons)

        self.app.api.calls.clear()
        self.cb(111, "tools")
        self.assertEqual(self.buttons(),
                         ["tools:report", "tools:engagement", "tools:buy", "tools:sub", "home"])

    def test_tool_access_back_navigation(self):
        self.onboard()
        self.app.api.calls.clear()
        self.cb(111, "tools")
        self.assertEqual(self.buttons(), ["tools:report", "tools:engagement", "tools:buy", "tools:sub", "home"])

        self.app.api.calls.clear()
        self.cb(111, "tools:report")
        self.assertIn("platform:telegram", self.buttons())
        self.assertEqual(self.buttons()[-1], "tools")

        self.app.api.calls.clear()
        self.cb(111, "platform:tiktok")
        self.assertIn("services", self.buttons())

        self.app.api.calls.clear()
        self.cb(111, "service:1")
        self.assertIn("platform:tiktok", self.buttons())

        self.app.api.calls.clear()
        self.cb(111, "platform:tiktok")
        self.assertIn("services", self.buttons())

        self.app.api.calls.clear()
        self.cb(111, "services")
        self.assertEqual(self.buttons()[-1], "tools")

        self.app.api.calls.clear()
        self.cb(111, "tools")
        self.assertEqual(self.buttons(), ["tools:report", "tools:engagement", "tools:buy", "tools:sub", "home"])

        self.app.api.calls.clear()
        self.cb(111, "tools:buy")
        tool_id = self.app.db.list_services("tools")[0]["id"]
        self.app.api.calls.clear()
        self.cb(111, f"service:{tool_id}")
        self.assertIn("tools:buy", self.buttons())

        self.app.api.calls.clear()
        self.cb(111, "tools:buy")
        self.assertEqual(self.buttons()[-1], "tools")

    def test_welcome_gif_on_start_after_onboarding(self):
        if not WELCOME_GIF.is_file():
            self.skipTest("assets/gifs/welcome.gif is missing")
        self.onboard()
        uploads = [c for c in self.app.api.calls if c[0] == "sendAnimationFile"]
        self.assertEqual(len(uploads), 1)
        self.assertIn("Chào mừng", uploads[0][2])
        self.assertEqual(self.app.db.get_setting("welcome_gif_id"), "welcome-file-id")
        self.assertTrue(self.app.db.get_setting("welcome_gif_sig"))

        self.app.api.calls.clear()
        self.msg(111, "/start")
        cached = [c for c in self.app.api.calls if c[0] == "sendAnimation"]
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0][1]["animation"], "welcome-file-id")

        self.app.api.calls.clear()
        self.msg(111, "/menu")
        self.assertFalse(any(c[0] in ("sendAnimation", "sendAnimationFile")
                             for c in self.app.api.calls))

    def test_tool_access_menu_sends_image(self):
        if not TOOLS_GIF.is_file():
            self.skipTest("assets/gifs/tools.gif is missing")
        self.onboard()
        self.app.api.calls.clear()
        self.cb(111, "tools")
        uploads = [c for c in self.app.api.calls if c[0] == "sendAnimationFile"]
        self.assertEqual(len(uploads), 1)
        self.assertIn("Tool Access", uploads[0][2])
        self.assertEqual(self.app.db.get_setting("tools_gif_id"), "tools-file-id")

        self.app.api.calls.clear()
        self.cb(111, "tools")
        self.assertFalse(any(c[0] == "sendAnimationFile" for c in self.app.api.calls))
        cached = [c for c in self.app.api.calls if c[0] == "sendAnimation"]
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0][1]["animation"], "tools-file-id")
        self.assertEqual(self.buttons(), ["tools:report", "tools:engagement", "tools:buy", "tools:sub", "home"])

        self.app.api.calls.clear()
        self.msg(111, "/start")
        self.assertFalse(any(c[0] == "sendAnimationFile" for c in self.app.api.calls))
        welcome = [c for c in self.app.api.calls if c[0] == "sendAnimation"]
        self.assertEqual(len(welcome), 1)
        self.assertEqual(welcome[0][1]["animation"], "welcome-file-id")

    def test_start_catalog_order_quote_pay(self):
        self.onboard()
        self.cb(111, "tools")
        self.cb(111, "tools:report")
        self.cb(111, "platform:tiktok")
        self.cb(111, "service:1")
        self.cb(111, "new:1")
        self.cb(111, "target:1:post")
        self.msg(111, "https://www.tiktok.com/@creator/video/1234567890")
        self.msg(111, "The content impersonates a real business and shows deceptive contact information.")
        self.msg(111, "Screenshot and policy details available")
        o = self.app.db.list_orders(111)[0]
        self.assertEqual(o["status"], "awaiting_quote")
        self.msg(111, "/quote 1 200000")  # non-admin may not change anything
        self.assertEqual(self.app.db.get_order(o["id"])["status"], "awaiting_quote")
        self.msg(999, "/quote 1 200000")
        self.assertEqual(self.app.db.get_order(o["id"])["status"], "awaiting_payment")
        self.msg(999, "/credit 111 200000")
        self.cb(111, f"pay:{o['id']}")
        self.assertEqual(self.app.db.get_order(o["id"])["status"], "pending_review")
        self.msg(999, f"/approve {o['id']}")
        self.msg(999, f"/done {o['id']}")
        self.assertEqual(self.app.db.get_order(o["id"])["status"], "completed")

    def test_deposit_workflow_and_cancel(self):
        self.onboard()
        self.cb(111, "deposit")
        self.msg(111, "50000")
        self.msg(111, photo=[{"file_id": "photo1", "width": 640, "height": 400}])
        dep = self.app.db.list_deposits()[0]
        self.msg(111, f"/approvedep {dep['id']}")  # guard
        self.assertEqual(self.app.db.get_user(111)["balance"], 0)
        self.msg(999, f"/approvedep {dep['id']}")
        self.assertEqual(self.app.db.get_user(111)["balance"], 50000)
        self.msg(999, f"/approvedep {dep['id']}")
        self.assertEqual(self.app.db.get_user(111)["balance"], 50000)

    def test_verification_rejects_wrong_answers_and_cannot_skip(self):
        self.msg(111, "/start")
        self.cb(111, "wallet")
        self.assertFalse(self.app.db.get_user(111)["verified_at"])
        self.msg(111, "-999")
        state, data = self.app.db.get_state(111)
        self.assertEqual(state, "captcha")
        self.assertEqual(data["tries"], 1)
        self.msg(111, "-999")
        self.msg(111, "-999")
        state, data = self.app.db.get_state(111)
        self.assertEqual(state, "captcha")
        self.assertEqual(data["tries"], 0)
        self.msg(111, str(data["a"] + data["b"]))
        self.assertTrue(self.app.db.get_user(111)["verified_at"])
        self.cb(111, "lang:en")
        self.assertEqual(self.app.db.get_user(111)["language"], "en")
        self.cb(111, "language")
        self.cb(111, "lang:vi")
        self.assertEqual(self.app.db.get_user(111)["language"], "vi")

    def test_invalid_targets_and_media_greeting(self):
        self.onboard(language="en")
        self.cb(111, "target:5:channel")
        state, _ = self.app.db.get_state(111)
        self.assertEqual(state, "order_target")
        self.msg(111, "https://evil.example/watch?v=12")
        state, _ = self.app.db.get_state(111)
        self.assertEqual(state, "order_target")
        self.msg(111, "https://www.youtube.com/@examplechannel")
        state, _ = self.app.db.get_state(111)
        self.assertEqual(state, "order_reason")
        self.msg(999, "/setbanner", reply_to_message={"animation": {"file_id": "gif-id"}})
        self.msg(111, "/start")
        calls = [c for c in self.app.api.calls if c[0] == "sendAnimation"]
        self.assertTrue(calls)
        self.assertEqual(calls[-1][1]["animation"], "gif-id")
        self.assertIn("reply_markup", calls[-1][1])

    def test_no_bypass_before_language_selection(self):
        self.msg(111, "/start")
        state, data = self.app.db.get_state(111)
        self.msg(111, str(data["a"] + data["b"]))
        self.cb(111, "services")
        self.assertEqual(self.app.db.list_orders(111), [])
        self.cb(111, "lang:en")
        self.cb(111, "services")
        self.assertTrue(any("choose" in c[2].lower() or "platform" in c[2].lower()
                            for c in self.app.api.calls if c[0] == "sendMessage"))

    def test_telegram_members_ordering_flow(self):
        """Test full ordering flow: select service -> enter link -> enter qty -> confirm -> place order."""
        self.onboard(uid=111)
        # Give user enough balance for the order
        self.app.db.conn.execute("UPDATE users SET balance = ? WHERE user_id = ?", (50000, 111))
        
        # Navigate to Telegram Members
        self.cb(111, "tools")
        self.cb(111, "tools:engagement")
        self.cb(111, "engagement:telegram_members")

        # Select service 1720
        self.app.api.calls.clear()
        self.cb(111, "tg_member_select:1720")

        # Should ask for link
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("Nhập link" in t or "Enter" in t for t in texts))
        state, data = self.app.db.get_state(111)
        self.assertEqual(state, "tg_member_link")
        self.assertEqual(data["service_id"], "1720")

        # Enter valid group link
        self.app.api.calls.clear()
        self.msg(111, "https://t.me/testgroup")

        # Should ask for quantity
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng" in t.lower() or "quantity" in t.lower() for t in texts))
        state, data = self.app.db.get_state(111)
        self.assertEqual(state, "tg_member_qty")
        self.assertEqual(data["link"], "https://t.me/testgroup")

        # Enter valid quantity
        self.app.api.calls.clear()
        self.msg(111, "1000")

        # Should show confirmation
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("xác nhận" in t.lower() or "confirm" in t.lower() for t in texts))
        state, data = self.app.db.get_state(111)
        self.assertEqual(state, "tg_member_confirm")
        self.assertEqual(data["quantity"], 1000)
        # total = 1000 * 40.686 / 1000 = 40.686 VND, truncated to 40 VND
        self.assertEqual(data["total"], 40)

        # Confirm payment
        self.app.api.calls.clear()
        self.cb(111, "tg_member_confirm_pay")

        # Should show success
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("thành công" in t.lower() or "success" in t.lower() for t in texts))

        # Check order was created
        orders = self.app.db.list_orders(111)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["service_name"], "Tool Access")

        # Check provider order was created
        po = self.app.db.get_provider_order(orders[0]["id"])
        self.assertIsNotNone(po)
        self.assertEqual(po["provider_service_id"], "1720")
        self.assertEqual(po["quantity"], 1000)
        self.assertEqual(po["amount"], 40)

    def prepare_tg_member_order(self, uid=111, quantity="1000", balance=50000):
        self.onboard(uid=uid)
        self.app.db.conn.execute("UPDATE users SET balance=? WHERE user_id=?", (balance, uid))
        self.cb(uid, "tools")
        self.cb(uid, "tools:engagement")
        self.cb(uid, "engagement:telegram_members")
        self.cb(uid, "tg_member_select:1720")
        self.msg(uid, "https://t.me/testgroup")
        self.msg(uid, quantity)
        state, data = self.app.db.get_state(uid)
        self.assertEqual(state, "tg_member_confirm")
        return data

    def test_telegram_members_double_confirm_charges_once(self):
        self.prepare_tg_member_order(uid=111)
        self.cb(111, "tg_member_confirm_pay")
        self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(len(self.app.db.list_orders(111)), 1)
        self.assertEqual(self.app.db.one("SELECT COUNT(*) c FROM provider_orders")["c"], 1)
        self.assertEqual(self.app.db.get_user(111)["balance"], 49960)
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"], 1)

    def test_telegram_members_definitive_provider_error_refunds_once(self):
        self.prepare_tg_member_order(uid=111)
        provider = MockVietnamFB()

        def reject(**_kwargs):
            raise VietnamFBError("Provider từ chối dịch vụ", definitive=True)

        provider.add_order = reject
        self.app.provider = provider
        self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(self.app.db.get_user(111)["balance"], 50000)
        order = self.app.db.list_orders(111)[0]
        self.assertEqual(self.app.db.get_order(order["id"])["status"], "rejected")
        self.assertEqual(self.app.db.one("SELECT COUNT(*) c FROM provider_orders")["c"], 0)
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"], 1)
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 1)

    def test_telegram_members_ambiguous_error_keeps_charge_for_reconciliation(self):
        self.prepare_tg_member_order(uid=111)
        provider = MockVietnamFB()

        def timeout(**_kwargs):
            raise VietnamFBError("Network error: timed out", definitive=False)

        provider.add_order = timeout
        self.app.provider = provider
        self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(self.app.db.get_user(111)["balance"], 49960)
        order = self.app.db.list_orders(111)[0]
        self.assertEqual(self.app.db.get_order(order["id"])["status"], "pending_reconciliation")
        self.assertEqual(self.app.db.one("SELECT COUNT(*) c FROM provider_orders")["c"], 0)
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 0)
        admin_texts = [c[2] for c in self.app.api.calls
                       if c[0] == "sendMessage" and c[1] == 999]
        self.assertTrue(any("đối soát" in text.lower() for text in admin_texts))

    def test_telegram_members_db_failure_after_provider_does_not_refund(self):
        self.prepare_tg_member_order(uid=111)
        with patch.object(self.app.db, "attach_provider_order",
                          side_effect=RuntimeError("db down")), \
             patch("bot.time.sleep", return_value=None):
            self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(self.app.db.get_user(111)["balance"], 49960)
        order = self.app.db.list_orders(111)[0]
        self.assertEqual(self.app.db.get_order(order["id"])["status"], "pending_reconciliation")
        self.assertEqual(self.app.db.one("SELECT COUNT(*) c FROM provider_orders")["c"], 0)
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 0)
        admin_texts = [c[2] for c in self.app.api.calls
                       if c[0] == "sendMessage" and c[1] == 999]
        self.assertTrue(any("provider đã nhận đơn" in text.lower() for text in admin_texts))

    def test_telegram_members_lost_commit_recovers_order_without_double_debit(self):
        self.prepare_tg_member_order(uid=111)
        original = self.app.db.begin_provider_order

        def lost_response(**kwargs):
            original(**kwargs)
            raise RuntimeError("commit response lost")

        with patch.object(self.app.db, "begin_provider_order", side_effect=lost_response):
            self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(self.app.db.get_user(111)["balance"], 49960)
        orders = self.app.db.list_orders(111)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "processing")
        self.assertIsNotNone(self.app.db.get_provider_order(orders[0]["id"]))
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='provider_payment'")["c"], 1)

    def test_telegram_members_lost_refund_commit_is_not_treated_as_pending(self):
        self.prepare_tg_member_order(uid=111)
        provider = MockVietnamFB()

        def reject(**_kwargs):
            raise VietnamFBError("Provider từ chối", definitive=True)

        provider.add_order = reject
        self.app.provider = provider
        original = self.app.db.reject_order

        def lost_refund_response(order_id):
            original(order_id)
            raise RuntimeError("refund commit response lost")

        with patch.object(self.app.db, "reject_order", side_effect=lost_refund_response):
            self.cb(111, "tg_member_confirm_pay")
        self.assertEqual(self.app.db.get_user(111)["balance"], 50000)
        order = self.app.db.list_orders(111)[0]
        self.assertEqual(self.app.db.get_order(order["id"])["status"], "rejected")
        self.assertEqual(self.app.db.one(
            "SELECT COUNT(*) c FROM ledger WHERE kind='order_refund'")["c"], 1)

    def test_telegram_members_insufficient_balance(self):
        """Test ordering with insufficient balance."""
        self.onboard(uid=222)
        self.cb(222, "tools")
        self.cb(222, "tools:engagement")
        self.cb(222, "engagement:telegram_members")
        self.cb(222, "tg_member_select:1720")
        self.msg(222, "https://t.me/testgroup")
        self.msg(222, "10000")  # Large quantity = high cost

        # Should show insufficient balance
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("không đủ" in t.lower() or "insufficient" in t.lower() for t in texts))

    def test_telegram_members_invalid_link(self):
        """Test ordering with invalid link."""
        self.onboard(uid=333)
        self.cb(333, "tools")
        self.cb(333, "tools:engagement")
        self.cb(333, "engagement:telegram_members")
        self.cb(333, "tg_member_select:1720")

        # Enter invalid link
        self.msg(333, "not a valid link")

        # Should show error and stay in link state
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("không hợp lệ" in t.lower() or "invalid" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(333)
        self.assertEqual(state, "tg_member_link")

    def test_telegram_members_qty_invalid_format(self):
        """Test ordering with non-numeric quantity."""
        self.onboard(uid=343)
        self.cb(343, "tools")
        self.cb(343, "tools:engagement")
        self.cb(343, "engagement:telegram_members")
        self.cb(343, "tg_member_select:1720")
        self.msg(343, "https://t.me/testgroup")

        # Enter non-numeric quantity
        self.msg(343, "abc")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(343)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_zero(self):
        """Test ordering with zero quantity."""
        self.onboard(uid=344)
        self.cb(344, "tools")
        self.cb(344, "tools:engagement")
        self.cb(344, "engagement:telegram_members")
        self.cb(344, "tg_member_select:1720")
        self.msg(344, "https://t.me/testgroup")

        # Enter zero quantity
        self.msg(344, "0")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(344)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_negative(self):
        """Test ordering with negative quantity."""
        self.onboard(uid=345)
        self.cb(345, "tools")
        self.cb(345, "tools:engagement")
        self.cb(345, "engagement:telegram_members")
        self.cb(345, "tg_member_select:1720")
        self.msg(345, "https://t.me/testgroup")

        # Enter negative quantity
        self.msg(345, "-10")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(345)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_decimal(self):
        """Test ordering with decimal quantity."""
        self.onboard(uid=346)
        self.cb(346, "tools")
        self.cb(346, "tools:engagement")
        self.cb(346, "engagement:telegram_members")
        self.cb(346, "tg_member_select:1720")
        self.msg(346, "https://t.me/testgroup")

        # Enter decimal quantity
        self.msg(346, "10.5")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(346)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_below_min(self):
        """Test ordering with quantity below minimum."""
        self.onboard(uid=347)
        self.cb(347, "tools")
        self.cb(347, "tools:engagement")
        self.cb(347, "engagement:telegram_members")
        self.cb(347, "tg_member_select:1720")
        self.msg(347, "https://t.me/testgroup")

        # Enter quantity below min (service 1720 has min=10)
        self.msg(347, "5")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(347)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_above_max(self):
        """Test ordering with quantity above maximum."""
        self.onboard(uid=348)
        self.cb(348, "tools")
        self.cb(348, "tools:engagement")
        self.cb(348, "engagement:telegram_members")
        self.cb(348, "tg_member_select:1720")
        self.msg(348, "https://t.me/testgroup")

        # Enter quantity above max (service 1720 has max=1000000)
        self.msg(348, "2000000")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        self.assertTrue(any("số lượng không hợp lệ" in t.lower() or "invalid quantity" in t.lower() for t in texts))
        state, _ = self.app.db.get_state(348)
        self.assertEqual(state, "tg_member_qty")

    def test_telegram_members_qty_valid_shows_confirmation(self):
        """Test valid quantity shows professional confirmation with buttons."""
        self.onboard(uid=349)
        # Give user enough balance
        self.app.db.conn.execute("UPDATE users SET balance = ? WHERE user_id = ?", (50000, 349))
        
        self.cb(349, "tools")
        self.cb(349, "tools:engagement")
        self.cb(349, "engagement:telegram_members")
        self.cb(349, "tg_member_select:1720")
        self.msg(349, "https://t.me/testgroup")

        # Enter valid quantity
        self.msg(349, "1000")
        texts = [c[2] for c in self.app.api.calls if c[0] == "sendMessage"]
        # Should show "THÔNG TIN HỢP LỆ" confirmation
        self.assertTrue(any("thông tin hợp lệ" in t.lower() or "valid information" in t.lower() for t in texts))
        # Should have confirm and cancel buttons
        calls = [c for c in self.app.api.calls if c[0] == "sendMessage" and len(c) > 3 and c[3] is not None]
        self.assertTrue(len(calls) > 0, "Expected a sendMessage call with reply_markup")
        last_call = calls[-1]
        markup = last_call[3]  # 4th element is markup
        self.assertTrue(len(markup["inline_keyboard"]) > 0)
        state, _ = self.app.db.get_state(349)
        self.assertEqual(state, "tg_member_confirm")


if __name__ == "__main__":
    unittest.main()