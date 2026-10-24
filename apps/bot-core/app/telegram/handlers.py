"""Message handlers for Bot Core."""
from __future__ import annotations

import html
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import BotConfig
from app.core.state import StateManager, States, UserState
from app.database.connection import Database
from app.i18n import LANGUAGES, translate
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.modules.deposits.repository import DepositRepository
from app.modules.orders.repository import OrderRepository
from app.modules.orders.services_repository import ServicesRepository
from app.modules.engagement.repository import EngagementRepository
from app.modules.admin.repository import SettingsRepository
from app.telegram.keyboards import (
    build_home_keyboard, build_tools_keyboard, build_engagement_platforms_keyboard,
    build_engagement_categories_keyboard, build_member_packages_keyboard,
    build_cancel_keyboard, build_confirm_keyboard, build_back_keyboard,
)
from app.clients.engagement import EngagementClient, OrderRequest

LOG = logging.getLogger("botcore.handlers")


@dataclass
class Update:
    """Parsed Telegram update."""
    user_id: int
    username: str
    display_name: str
    message_id: int | None
    text: str | None
    callback_query_id: str | None
    callback_data: str | None
    is_callback: bool


class Handlers:
    """Main message and callback handlers."""

    def __init__(
        self,
        config: BotConfig,
        db: Database,
        tg_client,
        user_repo: UserRepository,
        wallet_repo: WalletRepository,
        deposit_repo: DepositRepository,
        order_repo: OrderRepository,
        services_repo: ServicesRepository,
        engagement_repo: EngagementRepository,
        settings_repo: SettingsRepository,
        state_manager: StateManager,
        engagement_client: EngagementClient,
    ):
        self.config = config
        self.db = db
        self.tg = tg_client
        self.user_repo = user_repo
        self.wallet_repo = wallet_repo
        self.deposit_repo = deposit_repo
        self.order_repo = order_repo
        self.services_repo = services_repo
        self.engagement_repo = engagement_repo
        self.settings_repo = settings_repo
        self.state_manager = state_manager
        self.engagement_client = engagement_client

    def handle_update(self, update: Update) -> None:
        """Route update to appropriate handler."""
        uid = update.user_id

        # Ensure user exists
        self.user_repo.ensure_user(uid, update.username, update.display_name)
        user = self.user_repo.get_user(uid)
        lang = user["language"] if user and user["language"] else "vi"

        t = lambda key, **kw: translate(lang, key, **kw)

        if update.is_callback:
            self._handle_callback(update, uid, lang, t)
        else:
            self._handle_message(update, uid, lang, t)

    def _handle_callback(self, update: Update, uid: int, lang: str, t) -> None:
        """Handle callback query."""
        data = update.callback_data
        cb_id = update.callback_query_id

        if not data or not cb_id:
            return

        self.tg.answer_callback_query(cb_id)

        # Language selection
        if data.startswith("lang:"):
            lang_code = data.split(":", 1)[1]
            if lang_code in LANGUAGES:
                self.user_repo.set_language(uid, lang_code)
                self._send_home(uid, lang_code)
            return

        # Main navigation
        if data == "home":
            self._send_home(uid, lang)
            return

        if data == "wallet":
            self._show_wallet(uid, lang, t)
            return

        if data == "tools":
            self._show_tools(uid, lang, t)
            return

        if data == "support":
            self._show_support(uid, lang, t)
            return

        if data == "referral":
            self._show_referral(uid, lang, t)
            return

        if data == "faq":
            self._show_faq(uid, lang, t)
            return

        if data == "changelog":
            self._show_changelog(uid, lang, t)
            return

        if data == "orders":
            self._show_orders(uid, lang, t)
            return

        if data == "language":
            self._show_language(uid, lang, t)
            return

        # Tools submenu
        if data == "tools:report":
            self._start_report_flow(uid, lang, t)
            return

        if data == "tools:engagement":
            self._show_engagement_platforms(uid, lang, t)
            return

        if data == "tools:buy":
            self._show_tool_buy(uid, lang, t)
            return

        if data == "tools:sub":
            self._show_tool_sub(uid, lang, t)
            return

        # Engagement platforms
        if data.startswith("engagement:platform:"):
            platform_slug = data.split(":", 2)[2]
            self._show_engagement_categories(uid, lang, t, platform_slug)
            return

        if data.startswith("engagement:coming_soon:"):
            platform_slug = data.split(":", 2)[2]
            platform = self.engagement_repo.get_platform_by_slug(platform_slug)
            name = platform["name"] if platform else platform_slug
            self.tg.send_message(uid, f"🚧 {name} {t('engagement_coming_soon')}")
            return

        # Engagement categories
        if data.startswith("engagement:category:"):
            cat_id = int(data.split(":", 2)[2])
            self._show_category_services(uid, lang, t, cat_id)
            return

        # Telegram member packages
        if data.startswith("tg_member_select:"):
            svc_id = int(data.split(":", 1)[1])
            self._show_tg_member_confirm(uid, lang, t, svc_id)
            return

        if data.startswith("tg_member_confirm_pay:"):
            parts = data.split(":")
            svc_id = int(parts[1])
            link = parts[2] if len(parts) > 2 else ""
            qty = int(parts[3]) if len(parts) > 3 else 0
            self._process_tg_member_order(uid, lang, t, svc_id, link, qty)
            return

        # Deposits
        if data == "deposit":
            self._start_deposit(uid, lang, t)
            return

        if data == "cancel_deposit":
            state = self.state_manager.get_state(uid)
            if state.name == States.DEPOSIT_AMOUNT:
                self.state_manager.clear_state(uid)
                self._show_wallet(uid, lang, t)
            return

        # Admin
        if data.startswith("admin:"):
            self._handle_admin(uid, lang, t, data)
            return

    def _handle_message(self, update: Update, uid: int, lang: str, t) -> None:
        """Handle text message."""
        text = (update.text or "").strip()

        # Command handling
        if text.startswith("/"):
            self._handle_command(uid, lang, t, text)
            return

        # State-based handling
        state = self.state_manager.get_state(uid)

        if state.name == States.CAPTCHA:
            self._handle_captcha(uid, lang, t, text, state)
            return

        if state.name == States.DEPOSIT_AMOUNT:
            self._handle_deposit_amount(uid, lang, t, text, state)
            return

        if state.name == States.DEPOSIT_PROOF:
            self._handle_deposit_proof(uid, lang, t, text, state)
            return

        if state.name == States.SUPPORT:
            self._handle_support_message(uid, lang, t, text)
            return

        if state.name == States.TG_MEMBER_LINK:
            self._handle_tg_member_link(uid, lang, t, text, state)
            return

        if state.name == States.TG_MEMBER_QTY:
            self._handle_tg_member_qty(uid, lang, t, text, state)
            return

        # Report flow states
        if state.name == States.ORDER_TARGET:
            self._handle_report_target(uid, lang, t, text, state)
            return

        if state.name == States.ORDER_REASON:
            self._handle_report_reason(uid, lang, t, text, state)
            return

        if state.name == States.ORDER_EVIDENCE:
            self._handle_report_evidence(uid, lang, t, text, state)
            return

        # Unknown message
        self.tg.send_message(uid, t("home", name=html.escape(update.display_name)), build_home_keyboard(t))

    def _handle_command(self, uid: int, lang: str, t, text: str) -> None:
        """Handle bot commands."""
        cmd = text.split()[0].lower()

        if cmd == "/start":
            if text == "/start":
                self._start_captcha(uid, lang, t)
            else:
                # Deep link referral
                ref = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""
                if ref.isdigit():
                    ref_id = int(ref)
                    self.user_repo.ensure_user(uid, "", "", ref_id if ref_id != uid else None)
                self._start_captcha(uid, lang, t)
            return

        if cmd == "/cancel":
            self.state_manager.clear_state(uid)
            self._send_home(uid, lang)
            return

        if cmd in ("/help", "/menu"):
            self._send_home(uid, lang)
            return

        if cmd == "/wallet":
            self._show_wallet(uid, lang, t)
            return

        if cmd == "/orders":
            self._show_orders(uid, lang, t)
            return

        # Admin commands
        if uid in self.config.admin_ids:
            if cmd == "/admin":
                self._show_admin_panel(uid, lang, t)
                return
            if cmd.startswith("/approve "):
                self._admin_approve_deposit(uid, lang, t, text)
                return
            if cmd.startswith("/reject "):
                self._admin_reject_deposit(uid, lang, t, text)
                return
            if cmd.startswith("/markup "):
                self._admin_set_markup(uid, lang, t, text)
                return

    # --- Implementation methods ---

    def _start_captcha(self, uid: int, lang: str, t) -> None:
        a = secrets.randbelow(20) + 1
        b = secrets.randbelow(20) + 1
        self.state_manager.set_state(uid, States.CAPTCHA, expires_in=120, a=a, b=b, attempts=3)
        self.tg.send_message(uid, t("captcha", a=a, b=b), build_cancel_keyboard(t, "home"))

    def _handle_captcha(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        try:
            answer = int(text.strip())
            a = state.data.get("a", 0)
            b = state.data.get("b", 0)
            if answer == a + b:
                self.user_repo.verify_user(uid)
                self.state_manager.clear_state(uid)
                self.tg.send_message(uid, t("verified"), build_back_keyboard(t, t("choose_language"), "language"))
            else:
                attempts = state.data.get("attempts", 3) - 1
                if attempts <= 0:
                    self.state_manager.clear_state(uid)
                    self._start_captcha(uid, lang, t)
                else:
                    self.state_manager.set_state(uid, States.CAPTCHA, expires_in=120, a=a, b=b, attempts=attempts)
                    self.tg.send_message(uid, t("captcha_bad", remaining=attempts), build_cancel_keyboard(t, "home"))
        except ValueError:
            self.tg.send_message(uid, t("captcha_bad", remaining=state.data.get("attempts", 3)), build_cancel_keyboard(t, "home"))

    def _send_home(self, uid: int, lang: str) -> None:
        t = lambda key, **kw: translate(lang, key, **kw)
        user = self.user_repo.get_user(uid)
        name = html.escape(user["display_name"]) if user and user["display_name"] else "User"
        self.tg.send_message(uid, t("home", name=name), build_home_keyboard(t))

    def _show_wallet(self, uid: int, lang: str, t) -> None:
        balance = self.wallet_repo.get_balance(uid)
        text = f"💰 <b>Ví tiền</b>\n\nSố dư: <b>{balance:,} VNĐ</b>"
        markup = build_cancel_keyboard(t, "home")
        self.tg.send_message(uid, text, markup)

    def _show_tools(self, uid: int, lang: str, t) -> None:
        self.tg.send_message(uid, t("tool_menu"), build_tools_keyboard(t))

    def _show_engagement_platforms(self, uid: int, lang: str, t) -> None:
        platforms = self.engagement_repo.list_platforms()
        self.tg.send_message(uid, t("engagement_menu"), build_engagement_platforms_keyboard(t, platforms))

    def _show_engagement_categories(self, uid: int, lang: str, t, platform_slug: str) -> None:
        platform = self.engagement_repo.get_platform_by_slug(platform_slug)
        if not platform:
            self._show_engagement_platforms(uid, lang, t)
            return

        categories = self.engagement_repo.list_categories(platform["id"])
        if not categories:
            self.tg.send_message(uid, t("engagement_no_services"), build_back_keyboard(t, t("back_engagement"), "tools:engagement"))
            return

        self.tg.send_message(uid, t("engagement_select_category"), build_engagement_categories_keyboard(t, categories))

    def _show_category_services(self, uid: int, lang: str, t, category_id: int) -> None:
        category = self.engagement_repo.get_category(category_id)
        if not category:
            self._show_engagement_platforms(uid, lang, t)
            return

        services = self.engagement_repo.list_provider_services(category_id)
        if not services:
            self.tg.send_message(uid, t("engagement_no_services"), build_back_keyboard(t, t("back_engagement"), "tools:engagement"))
            return

        if category["slug"] == "members":
            packages = []
            for svc in services:
                price_per_1000 = svc["rate_milli"]
                total_per_1000 = price_per_1000 * 2  # 100% markup
                button_text = f"{svc['name']} - {total_per_1000:,} VNĐ/1K"
                packages.append({"service_id": svc["id"], "button_text": button_text})

            self.tg.send_message(uid, t("tg_member_select"), build_member_packages_keyboard(t, packages))
        else:
            self.tg.send_message(uid, f"🚧 {category['name']} đang phát triển.")

    def _show_tg_member_confirm(self, uid: int, lang: str, t, svc_id: int) -> None:
        svc = self.engagement_repo.get_provider_service(svc_id)
        if not svc:
            self._show_engagement_platforms(uid, lang, t)
            return

        price_per_1000 = svc["rate_milli"] * 2  # 100% markup
        text = (f"📦 <b>{html.escape(svc['name'])}</b>\n\n"
                f"💰 Giá: {price_per_1000:,} VNĐ/1.000 member\n"
                f"📉 Tối thiểu: {svc['min_quantity']}\n"
                f"📈 Tối đa: {svc['max_quantity']}\n\n"
                f"{t('tg_member_enter_link')}")

        self.state_manager.set_state(uid, States.TG_MEMBER_LINK, expires_in=300, svc_id=svc_id)
        self.tg.send_message(uid, text, build_cancel_keyboard(t, "engagement:platform:telegram"))

    def _handle_tg_member_link(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        link = text.strip()
        if not (link.startswith("https://t.me/") or link.startswith("@")):
            self.tg.send_message(uid, t("tg_member_invalid_link"), build_cancel_keyboard(t, "engagement:platform:telegram"))
            return

        svc_id = state.data.get("svc_id")
        svc = self.engagement_repo.get_provider_service(svc_id)
        if not svc:
            self.state_manager.clear_state(uid)
            self._show_engagement_platforms(uid, lang, t)
            return

        self.state_manager.set_state(uid, States.TG_MEMBER_QTY, expires_in=300, svc_id=svc_id, link=link)
        self.tg.send_message(uid, t("tg_member_enter_qty", min_qty=svc["min_quantity"], max_qty=svc["max_quantity"]), build_cancel_keyboard(t, "engagement:platform:telegram"))

    def _handle_tg_member_qty(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        try:
            qty = int(text.strip())
        except ValueError:
            self.tg.send_message(uid, t("tg_member_qty_invalid_format", min_qty=state.data.get("min_qty", 1), max_qty=state.data.get("max_qty", 1000000)), build_cancel_keyboard(t, "engagement:platform:telegram"))
            return

        svc_id = state.data.get("svc_id")
        link = state.data.get("link")
        svc = self.engagement_repo.get_provider_service(svc_id)
        if not svc:
            self.state_manager.clear_state(uid)
            self._show_engagement_platforms(uid, lang, t)
            return

        if qty < svc["min_quantity"]:
            self.tg.send_message(uid, t("tg_member_qty_below_min", service_name=svc["name"], quantity=qty, min_qty=svc["min_quantity"], max_qty=svc["max_quantity"]), build_cancel_keyboard(t, "engagement:platform:telegram"))
            return

        if qty > svc["max_quantity"]:
            self.tg.send_message(uid, t("tg_member_qty_above_max", service_name=svc["name"], quantity=qty, min_qty=svc["min_quantity"], max_qty=svc["max_quantity"]), build_cancel_keyboard(t, "engagement:platform:telegram"))
            return

        if qty <= 0:
            self.tg.send_message(uid, t("tg_member_qty_zero", service_name=svc["name"], min_qty=svc["min_quantity"], max_qty=svc["max_quantity"]), build_cancel_keyboard(t, "engagement:platform:telegram"))
            return

        # Show confirmation
        price_per_1000 = svc["rate_milli"] * 2
        total = (price_per_1000 * qty) // 1000
        text = t("tg_member_qty_valid", service_name=svc["name"], link=link, quantity=qty, total=total)
        confirm_data = f"tg_member_confirm_pay:{svc_id}:{link}:{qty}"
        self.tg.send_message(uid, text, build_confirm_keyboard(t, confirm_data, "engagement:platform:telegram"))

    def _process_tg_member_order(self, uid: int, lang: str, t, svc_id: int, link: str, qty: int) -> None:
        svc = self.engagement_repo.get_provider_service(svc_id)
        if not svc:
            self.tg.send_message(uid, t("tg_member_unavailable"))
            return

        price_per_1000 = svc["rate_milli"] * 2
        total = (price_per_1000 * qty) // 1000

        # Check balance
        balance = self.wallet_repo.get_balance(uid)
        if balance < total:
            self.tg.send_message(uid, t("tg_member_insufficient_balance", need=total, have=balance))
            return

        # Place order via Engagement API
        self.tg.send_message(uid, t("tg_member_placing"))

        request = OrderRequest(
            service_id=svc_id,
            quantity=qty,
            link=link,
            idempotency_key=f"tg_{uid}_{svc_id}_{qty}_{int(time.time())}",
        )
        result = self.engagement_client.place_order(request)

        if not result.success:
            if "timeout" in str(result.error).lower():
                self.tg.send_message(uid, t("tg_member_timeout"))
            else:
                self.tg.send_message(uid, t("tg_member_api_error", error=str(result.error)[:200]))
            return

        # Create local order
        request_key = f"tg_member_{uid}_{svc_id}_{result.provider_order_id}"
        status, order = self.order_repo.begin_provider_order(
            user_id=uid,
            service_id=svc_id,
            request_key=request_key,
            subject=link,
            evidence=f"qty:{qty}",
            amount=total,
        )

        if status == "duplicate":
            self.tg.send_message(uid, t("tg_member_duplicate"))
            return

        if status == "insufficient":
            self.tg.send_message(uid, t("tg_member_insufficient_balance", need=total, have=balance))
            return

        if status != "ok" or not order:
            self.tg.send_message(uid, t("tg_member_failed", error="internal error"))
            return

        # Attach provider order
        markup = self.settings_repo.get_markup_percent()
        self.order_repo.attach_provider_order(
            order_id=order["id"],
            provider_name="vietnamfb",
            provider_service_id=svc["provider_service_id"],
            provider_order_id=result.provider_order_id,
            quantity=qty,
            link=link,
            unit_price_milli=svc["rate_milli"],
            markup_percent=markup,
            api_price_per_1000_milli=svc["rate_milli"],
            api_response={"charge_milli": result.charge_milli, "status": result.status},
        )

        self.tg.send_message(uid, t("tg_member_success", order_id=order["id"], service_name=svc["name"], link=link, quantity=qty, total=total))

    def _start_deposit(self, uid: int, lang: str, t) -> None:
        self.state_manager.set_state(uid, States.DEPOSIT_AMOUNT, expires_in=300)
        text = f"💳 <b>Nạp tiền</b>\n\nNhập số tiền muốn nạp (10.000 - 100.000.000 VNĐ):"
        self.tg.send_message(uid, text, build_cancel_keyboard(t, "wallet"))

    def _handle_deposit_amount(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        try:
            amount = int(re.sub(r"[.,\s]", "", text))
            if not (10000 <= amount <= 100000000):
                raise ValueError
        except ValueError:
            self.tg.send_message(uid, t("tg_member_qty_invalid_format", min_qty=10000, max_qty=100000000), build_cancel_keyboard(t, "wallet"))
            return

        dep = self.deposit_repo.create(uid, amount)
        if not dep:
            self.tg.send_message(uid, "Bạn đã có quá nhiều yêu cầu nạp đang chờ. Dùng /cancel để trở về menu.")
            self.state_manager.clear_state(uid)
            return

        self.state_manager.set_state(uid, States.DEPOSIT_PROOF, expires_in=3600, deposit_id=dep["id"])
        bank_name = self.config.bank_name
        bank_account = self.config.bank_account
        bank_owner = self.config.bank_owner
        self.tg.send_message(uid, f"<b>Thông tin chuyển khoản</b>\nNgân hàng: {html.escape(bank_name)}\n"
                         f"Chủ tài khoản: {html.escape(bank_owner)}\nSTK: <code>{html.escape(bank_account)}</code>\n"
                         f"Số tiền: <b>{amount:,} VNĐ</b>\n"
                         f"Nội dung CK: <code>TN{dep['id']}</code>\n\n"
                         "Sau khi chuyển khoản, gửi <b>ảnh chứng từ hoặc mã giao dịch</b> tại đây. "
                         "Hệ thống không tự ghi có nếu chưa được đối chiếu tại ngân hàng.")

    def _handle_deposit_proof(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        deposit_id = state.data.get("deposit_id")
        dep = self.deposit_repo.submit_proof(deposit_id, uid, "text", text)
        if not dep:
            self.tg.send_message(uid, "Không tìm thấy yêu cầu nạp hoặc đã được xử lý.")
            self.state_manager.clear_state(uid)
            return
        self.tg.send_message(uid, "✅ Đã nhận chứng từ nạp tiền. Admin sẽ đối chiếu và duyệt trong thời gian sớm nhất.")
        self.state_manager.clear_state(uid)

    def _show_support(self, uid: int, lang: str, t) -> None:
        self.state_manager.set_state(uid, States.SUPPORT, expires_in=3600)
        self.tg.send_message(uid, "💬 <b>Hỗ trợ</b>\n\nGửi tin nhắn, ảnh hoặc file mô tả vấn đề. Admin sẽ phản hồi sớm nhất.", build_cancel_keyboard(t, "home"))

    def _handle_support_message(self, uid: int, lang: str, t, text: str) -> None:
        self.db.execute(
            "INSERT INTO tickets(user_id, message, created_at) VALUES (?,?,?)",
            (uid, text, self.db.utcnow()),
        )
        self.tg.send_message(uid, "✅ Đã gửi yêu cầu hỗ trợ. Admin sẽ liên hệ lại.", build_back_keyboard(t, t("back"), "home"))
        self.state_manager.clear_state(uid)

    def _show_referral(self, uid: int, lang: str, t) -> None:
        count = self.user_repo.get_referral_count(uid)
        bot_username = self.tg.username
        link = f"https://t.me/{bot_username}?start={uid}" if bot_username else "N/A"
        text = (f"🤝 <b>Chương trình giới thiệu</b>\n\n"
                f"Số người giới thiệu: <b>{count}</b>\n"
                f"Link giới thiệu: <code>{link}</code>\n\n"
                f"Chia sẻ link để nhận thưởng khi bạn bè tham gia!")
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_faq(self, uid: int, lang: str, t) -> None:
        text = ("❓ <b>FAQ</b>\n\n"
                "1. <b>Cách đặt hàng?</b> Chọn dịch vụ → Nhập link/số lượng → Xác nhận → Thanh toán từ ví.\n"
                "2. <b>Nạp tiền?</b> Vào Ví tiền → Nạp tiền → Chuyển khoản → Gửi chứng từ.\n"
                "3. <b>Hoàn tiền?</b> Tự động khi đơn bị từ chối hoặc lỗi provider xác thực.\n"
                "4. <b>Liên hệ Admin?</b> Dùng mục Hỗ trợ trên menu chính.")
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_changelog(self, uid: int, lang: str, t) -> None:
        text = ("📋 <b>Cập nhật gần đây</b>\n\n"
                "• Tách Engagement API thành service riêng\n"
                "• Hỗ trợ đa nền tảng: Telegram, YouTube, Twitter, Facebook, Instagram, Shopee\n"
                "• Cải thiện bảo mật và hiệu suất")
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_orders(self, uid: int, lang: str, t) -> None:
        orders = self.order_repo.list_user_orders(uid)
        if not orders:
            text = "📋 <b>Đơn của tôi</b>\n\nChưa có đơn hàng nào."
        else:
            lines = ["📋 <b>Đơn của tôi</b>\n"]
            for o in orders:
                lines.append(f"#{o['id']} | {o['service_name']} | {o['amount']:,} VNĐ | {o['status']}")
            text = "\n".join(lines)
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_language(self, uid: int, lang: str, t) -> None:
        rows = []
        for code, name in LANGUAGES.items():
            mark = " ✅" if code == lang else ""
            rows.append(((f"{name}{mark}", f"lang:{code}"),))
        rows.append(((t("back"), "home"),))
        self.tg.send_message(uid, t("choose_language"), {"inline_keyboard": rows})

    def _show_tool_buy(self, uid: int, lang: str, t) -> None:
        services = self.services_repo.list("tools")
        if not services:
            self.tg.send_message(uid, t("tool_sub_none"), build_back_keyboard(t, t("back_tools"), "tools"))
            return
        text = t("tool_menu")
        rows = []
        for svc in services:
            rows.append(((f"{svc['title']} - {svc['price']:,} VNĐ", f"tool_buy:{svc['id']}"),))
        rows.append(((t("back_tools"), "tools"),))
        self.tg.send_message(uid, text, {"inline_keyboard": rows})

    def _show_tool_sub(self, uid: int, lang: str, t) -> None:
        text = t("tool_sub_title") + "\n\n" + t("tool_sub_none") + "\n\n" + t("tool_sub_note")
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back_tools"), "tools"))

    def _start_report_flow(self, uid: int, lang: str, t) -> None:
        # Show platform selection
        platforms = self.engagement_repo.list_platforms()
        self.tg.send_message(uid, t("choose_platform"), build_engagement_platforms_keyboard(t, platforms))

    def _handle_report_target(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        # Simplified for now
        self.state_manager.clear_state(uid)
        self.tg.send_message(uid, "Tính năng báo cáo đang phát triển.", build_back_keyboard(t, t("back"), "home"))

    def _handle_report_reason(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        self.state_manager.clear_state(uid)
        self.tg.send_message(uid, "Tính năng báo cáo đang phát triển.", build_back_keyboard(t, t("back"), "home"))

    def _handle_report_evidence(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        self.state_manager.clear_state(uid)
        self.tg.send_message(uid, "Tính năng báo cáo đang phát triển.", build_back_keyboard(t, t("back"), "home"))

    def _show_admin_panel(self, uid: int, lang: str, t) -> None:
        markup = keyboard(
            (("📋 Pending Deposits", "admin:deposits"), ("📦 All Orders", "admin:orders")),
            (("💰 Set Markup", "admin:markup"), ("📊 Stats", "admin:stats")),
        )
        self.tg.send_message(uid, "🔧 <b>Admin Panel</b>", markup)

    def _handle_admin(self, uid: int, lang: str, t, data: str) -> None:
        if uid not in self.config.admin_ids:
            return
        if data == "admin:deposits":
            deposits = self.deposit_repo.list_pending_deposits()
            text = "📋 <b>Pending Deposits</b>\n\n"
            for d in deposits:
                text += f"#{d['id']} | User: {d['user_id']} | {d['amount']:,} VNĐ | {d['status']}\n"
            self.tg.send_message(uid, text, build_back_keyboard(t, "← Admin", "admin:panel"))
        elif data == "admin:orders":
            orders = self.order_repo.list_all_orders()
            text = "📦 <b>All Orders</b>\n\n"
            for o in orders:
                text += f"#{o['id']} | User: {o['user_id']} | {o['service_name']} | {o['amount']:,} VNĐ | {o['status']}\n"
            self.tg.send_message(uid, text, build_back_keyboard(t, "← Admin", "admin:panel"))
        elif data == "admin:markup":
            markup = self.settings_repo.get_markup_percent()
            self.tg.send_message(uid, f"Current markup: {markup}%\nUse /markup <percent> to change.")
        elif data == "admin:stats":
            users = self.db.fetchone("SELECT COUNT(*) c FROM users")["c"]
            balance = self.db.fetchone("SELECT SUM(balance) s FROM users")["s"] or 0
            orders = self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"]
            self.tg.send_message(uid, f"👥 Users: {users}\n💰 Total Balance: {balance:,} VNĐ\n📦 Orders: {orders}")

    def _admin_approve_deposit(self, uid: int, lang: str, t, text: str) -> None:
        try:
            dep_id = int(text.split()[1])
            dep = self.deposit_repo.approve(dep_id)
            if dep:
                self.tg.send_message(uid, f"✅ Approved deposit #{dep_id}")
            else:
                self.tg.send_message(uid, "❌ Deposit not found or not pending")
        except (IndexError, ValueError):
            self.tg.send_message(uid, "Usage: /approve <deposit_id>")

    def _admin_reject_deposit(self, uid: int, lang: str, t, text: str) -> None:
        try:
            dep_id = int(text.split()[1])
            dep = self.deposit_repo.reject(dep_id)
            if dep:
                self.tg.send_message(uid, f"❌ Rejected deposit #{dep_id}")
            else:
                self.tg.send_message(uid, "❌ Deposit not found or not pending")
        except (IndexError, ValueError):
            self.tg.send_message(uid, "Usage: /reject <deposit_id>")

    def _admin_set_markup(self, uid: int, lang: str, t, text: str) -> None:
        try:
            percent = int(text.split()[1])
            if self.settings_repo.set_markup_percent(percent):
                self.tg.send_message(uid, f"✅ Markup set to {percent}%")
            else:
                self.tg.send_message(uid, "❌ Invalid percentage")
        except (IndexError, ValueError):
            self.tg.send_message(uid, "Usage: /markup <percent>")