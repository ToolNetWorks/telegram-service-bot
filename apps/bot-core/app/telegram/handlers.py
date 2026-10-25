"""Message and callback handlers for Bot Core.

Telegram UI lives here.  Catalog data is fetched from the Engagement API; no
provider IDs, provider prices or category lists are hardcoded in this module.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.clients.engagement import EngagementAPIError, EngagementClient, OrderRequest, OrderResult
from app.core.config import BotConfig
from app.core.state import StateManager, States, UserState
from app.database.connection import Database
from app.i18n import LANGUAGES, translate
from app.modules.admin.repository import SettingsRepository
from app.modules.deposits.repository import DepositRepository
from app.modules.engagement.repository import EngagementRepository
from app.modules.orders.repository import OrderRepository
from app.modules.orders.services_repository import ServicesRepository
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.telegram.keyboards import (
    build_back_keyboard,
    build_cancel_keyboard,
    build_confirm_keyboard,
    build_engagement_categories_keyboard,
    build_engagement_platforms_keyboard,
    build_home_keyboard,
    build_service_packages_keyboard,
    build_tools_keyboard,
    keyboard,
    sale_price_per_1000,
)

LOG = logging.getLogger("botcore.handlers")

TELEGRAM_LINK_RE = re.compile(r"^(?:https://t\.me/[A-Za-z0-9_+]{3,}|@[A-Za-z0-9_]{3,})$")


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

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def handle_update(self, update: Update) -> None:
        uid = update.user_id
        self.user_repo.ensure_user(uid, update.username, update.display_name)
        user = self.user_repo.get_user(uid)
        lang = user["language"] if user and user["language"] else "vi"
        t = lambda key, **kw: translate(lang, key, **kw)

        if update.is_callback:
            self._handle_callback(update, uid, lang, t)
        else:
            self._handle_message(update, uid, lang, t)

    def _handle_callback(self, update: Update, uid: int, lang: str, t) -> None:
        data = update.callback_data
        cb_id = update.callback_query_id
        if not data or not cb_id:
            return

        self.tg.answer_callback_query(cb_id)

        if data.startswith("lang:"):
            lang_code = data.split(":", 1)[1]
            if lang_code in LANGUAGES:
                self.user_repo.set_language(uid, lang_code)
                # Check if we're in post-CAPTCHA language selection flow
                state = self.state_manager.get_state(uid)
                if state.name == "post_captcha_language":
                    pending_action = state.data.get("pending_action", "home")
                    self.state_manager.clear_state(uid)
                    self._execute_pending_action(uid, lang_code, lambda k, **kw: translate(lang_code, k, **kw), pending_action)
                else:
                    self._send_home(uid, lang_code)
            return

        # Public callbacks - no verification required
        if data == "home":
            self._send_home(uid, lang)
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
        if data == "language":
            self._show_language(uid, lang, t)
            return

        # Callbacks that require verification
        if data == "wallet":
            if not self._require_verification(uid, lang, t, "wallet"):
                return
            self._show_wallet(uid, lang, t)
            return
        if data == "orders":
            if not self._require_verification(uid, lang, t, "orders"):
                return
            self._show_orders(uid, lang, t)
            return
        if data == "tools:report":
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._start_report_flow(uid, lang, t)
            return
        if data == "tools:engagement":
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._show_engagement_platforms(uid, lang, t)
            return
        if data == "tools:buy":
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._show_tool_buy(uid, lang, t)
            return
        if data == "tools:sub":
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._show_tool_sub(uid, lang, t)
            return

        # Engagement navigation - require verification
        if data.startswith("engagement:platform:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._show_engagement_categories(uid, lang, t, data.split(":", 2)[2])
            return
        if data.startswith("engagement:coming_soon:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._show_coming_soon(uid, lang, t, data.split(":", 2)[2])
            return
        if data.startswith("engagement:category:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            try:
                category_id = int(data.split(":", 2)[2])
            except ValueError:
                self._show_engagement_platforms(uid, lang, t)
                return
            self._show_category_services(uid, lang, t, category_id)
            return
        if data.startswith("engagement:service:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            try:
                service_id = int(data.split(":", 2)[2])
            except ValueError:
                self._show_engagement_platforms(uid, lang, t)
                return
            self._start_engagement_order(uid, lang, t, service_id)
            return

        # Historical callbacks from messages sent before the API split.
        if data in ("engagement:telegram_members", "engagement:telegram_views"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            slug = "members" if data.endswith("members") else "views"
            self._show_category_by_slug(uid, lang, t, "telegram", slug)
            return
        if data.startswith("tg_member_select:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            try:
                service_id = int(data.split(":", 1)[1])
            except ValueError:
                self._show_engagement_platforms(uid, lang, t)
                return
            self._start_engagement_order(uid, lang, t, service_id)
            return

        # Order confirmation - requires verification
        if data == "engagement:confirm" or data == "tg_member_confirm_pay":
            if not self._require_verification(uid, lang, t, "services"):
                return
            self._confirm_engagement_order(uid, lang, t, None)
            return
        if data.startswith("tg_member_confirm_pay:"):
            if not self._require_verification(uid, lang, t, "services"):
                return
            # Legacy messages embedded service/link/quantity in callback_data.
            self._confirm_engagement_order(uid, lang, t, data)
            return

        # Deposit - requires verification
        if data == "deposit":
            if not self._require_verification(uid, lang, t, "wallet"):
                return
            self._start_deposit(uid, lang, t)
            return
        if data == "cancel_deposit":
            state = self.state_manager.get_state(uid)
            if state.name == States.DEPOSIT_AMOUNT:
                self.state_manager.clear_state(uid)
                if self._require_verification(uid, lang, t, "wallet"):
                    self._show_wallet(uid, lang, t)
            return
        if data.startswith("admin:"):
            # Admin callbacks require verification + admin check
            if uid not in self.config.admin_ids:
                return
            if not self._require_verification(uid, lang, t, "admin"):
                return
            self._handle_admin(uid, lang, t, data)
            return

    def _handle_message(self, update: Update, uid: int, lang: str, t) -> None:
        text = (update.text or "").strip()
        if text.startswith("/"):
            self._handle_command(uid, lang, t, text)
            return

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
        if state.name in (States.ENGAGEMENT_LINK, States.TG_MEMBER_LINK):
            self._handle_engagement_link(uid, lang, t, text, state)
            return
        if state.name in (States.ENGAGEMENT_QTY, States.TG_MEMBER_QTY):
            self._handle_engagement_qty(uid, lang, t, text, state)
            return
        if state.name in (States.ORDER_TARGET, States.ORDER_REASON, States.ORDER_EVIDENCE):
            self.state_manager.clear_state(uid)
            self.tg.send_message(uid, "🚧 Tính năng này đang phát triển.", build_back_keyboard(t, t("back"), "home"))
            return

        self.tg.send_message(uid, t("home", name=html.escape(update.display_name)), build_home_keyboard(t))

    def _handle_command(self, uid: int, lang: str, t, text: str) -> None:
        cmd = text.split()[0].lower()
        if cmd == "/start":
            if text != "/start":
                ref = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""
                if ref.isdigit():
                    ref_id = int(ref)
                    self.user_repo.ensure_user(uid, "", "", ref_id if ref_id != uid else None)
            # Check if user is already verified
            user = self.user_repo.get_user(uid)
            if user and user["verified_at"]:
                # User already verified, show home directly
                self._send_home(uid, lang)
                return
            # User not verified, start CAPTCHA with pending_action="home"
            self._start_captcha(uid, lang, t, pending_action="home")
            return
        if cmd == "/cancel":
            self.state_manager.clear_state(uid)
            self._send_home(uid, lang)
            return
        if cmd in ("/help", "/menu"):
            self._send_home(uid, lang)
            return
        # Commands that require verification
        if cmd in ("/wallet", "/orders"):
            pending_action = "wallet" if cmd == "/wallet" else "orders"
            if not self._require_verification(uid, lang, t, pending_action):
                return
            if cmd == "/wallet":
                self._show_wallet(uid, lang, t)
            else:
                self._show_orders(uid, lang, t)
            return
        if uid in self.config.admin_ids:
            if cmd == "/admin":
                # Admin panel requires verification + admin check
                if not self._require_verification(uid, lang, t, "admin"):
                    return
                self._show_admin_panel(uid, lang, t)
                return
            if cmd == "/approve":
                self._admin_approve_deposit(uid, lang, t, text)
                return
            if cmd == "/reject":
                self._admin_reject_deposit(uid, lang, t, text)
                return
            if cmd == "/markup":
                self._admin_set_markup(uid, lang, t, text)
                return

    # ------------------------------------------------------------------
    # Verification helpers
    # ------------------------------------------------------------------

    # Actions that require user verification
    _VERIFIED_ACTIONS: set[str] = {
        "wallet", "orders", "services", "admin", "engagement",
    }

    # Callback actions that require verification (mapped to pending_action)
    _VERIFIED_CALLBACKS: dict[str, str] = {
        "wallet": "wallet",
        "orders": "orders",
        "tools:engagement": "services",
        "tools:buy": "services",
        "tools:sub": "services",
        "tools:report": "services",
        "engagement:platform:telegram": "services",
        "engagement:platform:facebook": "services",
        "engagement:platform:instagram": "services",
        "engagement:platform:tiktok": "services",
        "engagement:platform:threads": "services",
        "engagement:platform:youtube": "services",
        "engagement:platform:twitter": "services",
        "engagement:platform:shopee": "services",
        "deposit": "wallet",
    }

    def _is_verified(self, uid: int) -> bool:
        """Check if user is verified (has verified_at in database)."""
        user = self.user_repo.get_user(uid)
        if not user:
            return False
        # sqlite3.Row doesn't have .get(), use dictionary access
        return bool(user["verified_at"])

    def _require_verification(self, uid: int, lang: str, t, pending_action: str) -> bool:
        """Check verification; if not verified, start CAPTCHA with pending_action.
        Returns True if user is verified and can proceed."""
        if self._is_verified(uid):
            return True
        # Not verified - start CAPTCHA with pending_action
        self._start_captcha(uid, lang, t, pending_action=pending_action)
        return False

    def _start_captcha(self, uid: int, lang: str, t, pending_action: str = "home") -> None:
        """Start CAPTCHA challenge with optional pending_action to resume after verification."""
        a = secrets.randbelow(20) + 1
        b = secrets.randbelow(20) + 1
        self.state_manager.set_state(
            uid,
            States.CAPTCHA,
            expires_in=120,
            a=a,
            b=b,
            attempts=3,
            pending_action=pending_action,
        )
        self.tg.send_message(uid, t("captcha", a=a, b=b), build_cancel_keyboard(t, "home"))

    def _handle_captcha(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        """Handle CAPTCHA answer. On success, verify user and resume pending_action."""
        pending_action = state.data.get("pending_action", "home")
        try:
            answer = int(text.strip())
            a = state.data.get("a", 0)
            b = state.data.get("b", 0)
            if answer == a + b:
                # CAPTCHA correct - verify user and resume pending action
                self.user_repo.verify_user(uid)
                self.state_manager.clear_state(uid)
                
                # Resume pending action
                self._resume_pending_action(uid, lang, t, pending_action)
            else:
                attempts = state.data.get("attempts", 3) - 1
                if attempts <= 0:
                    self.state_manager.clear_state(uid)
                    self._start_captcha(uid, lang, t, pending_action)
                else:
                    self.state_manager.set_state(
                        uid,
                        States.CAPTCHA,
                        expires_in=120,
                        a=a,
                        b=b,
                        attempts=attempts,
                        pending_action=pending_action,
                    )
                    self.tg.send_message(uid, t("captcha_bad", remaining=attempts), build_cancel_keyboard(t, "home"))
        except ValueError:
            self.tg.send_message(
                uid,
                t("captcha_bad", remaining=state.data.get("attempts", 3)),
                build_cancel_keyboard(t, "home"),
            )

    def _resume_pending_action(self, uid: int, lang: str, t, pending_action: str) -> None:
        """After successful verification, execute the pending action.
        If user hasn't selected a language yet, show language selection first."""
        user = self.user_repo.get_user(uid)
        user_lang = user["language"] if user else None
        
        # If no language selected yet, show language selection
        if not user_lang:
            # Store pending_action in state to resume after language selection
            self.state_manager.set_state(
                uid,
                "post_captcha_language",
                expires_in=300,
                pending_action=pending_action,
            )
            self.tg.send_message(uid, t("choose_language"), self._build_language_keyboard(t))
            return
        
        # Language already selected, proceed with pending action
        self._execute_pending_action(uid, user_lang, t, pending_action)

    def _execute_pending_action(self, uid: int, lang: str, t, pending_action: str) -> None:
        """Execute the pending action directly (language already selected)."""
        if pending_action == "home":
            self._send_home(uid, lang)
        elif pending_action == "wallet":
            self._show_wallet(uid, lang, t)
        elif pending_action == "orders":
            self._show_orders(uid, lang, t)
        elif pending_action == "services":
            self._show_engagement_platforms(uid, lang, t)
        elif pending_action == "admin":
            if uid in self.config.admin_ids:
                self._show_admin_panel(uid, lang, t)
            else:
                self._send_home(uid, lang)
        else:
            # Unknown action - default to home
            self._send_home(uid, lang)

    def _build_language_keyboard(self, t) -> dict:
        """Build inline keyboard for language selection."""
        rows = []
        for code, name in LANGUAGES.items():
            rows.append(((f"{name}", f"lang:{code}"),))
        rows.append(((t("cancel"), "home"),))
        return {"inline_keyboard": rows}

    def _send_home(self, uid: int, lang: str) -> None:
        t = lambda key, **kw: translate(lang, key, **kw)
        user = self.user_repo.get_user(uid)
        name = html.escape(user["display_name"]) if user and user["display_name"] else "User"
        self.tg.send_message(uid, t("home", name=name), build_home_keyboard(t))

    def _show_wallet(self, uid: int, lang: str, t) -> None:
        balance = self.wallet_repo.get_balance(uid)
        text = f"💰 <b>Ví tiền</b>\n\nSố dư: <b>{balance:,} VNĐ</b>"
        self.tg.send_message(uid, text, build_cancel_keyboard(t, "home"))

    def _show_tools(self, uid: int, lang: str, t) -> None:
        self.tg.send_message(uid, t("tool_menu"), build_tools_keyboard(t))

    # ------------------------------------------------------------------
    # Engagement Services UI (all catalog data comes from the API)
    # ------------------------------------------------------------------

    def _catalog_unavailable(self, uid: int, t, back_action: str = "tools") -> None:
        label = t("back_tools") if back_action == "tools" else t("back_engagement")
        self.tg.send_message(uid, t("engagement_api_unavailable"), build_back_keyboard(t, label, back_action))

    def _show_engagement_platforms(self, uid: int, lang: str, t) -> None:
        try:
            platforms = self.engagement_repo.list_platforms()
        except EngagementAPIError as exc:
            LOG.warning("Engagement catalog unavailable: %s", exc)
            self._catalog_unavailable(uid, t, "tools")
            return
        if not platforms:
            self._catalog_unavailable(uid, t, "tools")
            return
        self.tg.send_message(uid, t("engagement_menu"), build_engagement_platforms_keyboard(t, platforms))

    def _show_coming_soon(self, uid: int, lang: str, t, platform_slug: str) -> None:
        try:
            platform = self.engagement_repo.get_platform_by_slug(platform_slug)
        except EngagementAPIError:
            platform = None
        name = platform["name"] if platform else platform_slug
        self.tg.send_message(
            uid,
            f"🚧 <b>{html.escape(name)}</b>\n\n{t('engagement_updating')}",
            build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
        )

    def _show_engagement_categories(self, uid: int, lang: str, t, platform_slug: str) -> None:
        try:
            platform = self.engagement_repo.get_platform_by_slug(platform_slug)
            if not platform:
                self._show_engagement_platforms(uid, lang, t)
                return
            if not platform.get("enabled", True) or platform.get("coming_soon", False):
                self._show_coming_soon(uid, lang, t, platform_slug)
                return
            categories = self.engagement_repo.list_categories(platform_slug)
        except EngagementAPIError as exc:
            LOG.warning("Engagement categories unavailable: %s", exc)
            self._catalog_unavailable(uid, t, "tools:engagement")
            return

        if not categories:
            self.tg.send_message(
                uid,
                t("engagement_no_services"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return
        self.tg.send_message(
            uid,
            t("engagement_select_category"),
            build_engagement_categories_keyboard(t, categories),
        )

    def _show_category_by_slug(self, uid: int, lang: str, t, platform_slug: str, category_slug: str) -> None:
        try:
            categories = self.engagement_repo.list_categories(platform_slug)
        except EngagementAPIError:
            self._catalog_unavailable(uid, t, "tools:engagement")
            return
        category = next((item for item in categories if item.get("slug") == category_slug), None)
        if category is None:
            self.tg.send_message(
                uid,
                t("engagement_updating"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return
        self._show_category_services(uid, lang, t, category["id"])

    def _show_category_services(self, uid: int, lang: str, t, category_id: int) -> None:
        try:
            category = self.engagement_repo.get_category(category_id)
            if not category:
                self._show_engagement_platforms(uid, lang, t)
                return
            platform = self.engagement_repo.get_platform_by_slug(category["platform_slug"])
            if not platform:
                self._show_engagement_platforms(uid, lang, t)
                return
            if not category.get("enabled", True) or category.get("coming_soon", False):
                self.tg.send_message(
                    uid,
                    t("engagement_updating"),
                    build_back_keyboard(t, t("back_to_platform", platform=platform["name"]), f"engagement:platform:{platform['slug']}"),
                )
                return
            services = self.engagement_repo.list_provider_services(category_id)
        except EngagementAPIError as exc:
            LOG.warning("Engagement services unavailable: %s", exc)
            self._catalog_unavailable(uid, t, "tools:engagement")
            return

        if not services:
            self.tg.send_message(
                uid,
                t("engagement_updating"),
                build_back_keyboard(t, t("back_to_platform", platform=platform["name"]), f"engagement:platform:{platform['slug']}"),
            )
            return

        markup = self.settings_repo.get_markup_percent()
        lines = [t("engagement_choose_package", category=self._category_label(t, category))]
        for service in services:
            price = sale_price_per_1000(service.get("rate_milli", 0), markup)
            lines.append(
                f"• <b>{html.escape(service.get('name', 'Service'))}</b> — {price:,} VNĐ/1K\n"
                f"  Min {service.get('min_quantity', 1):,} · Max {service.get('max_quantity', 0):,}"
            )
        self.tg.send_message(
            uid,
            "\n".join(lines),
            build_service_packages_keyboard(
                t,
                services,
                platform_slug=platform["slug"],
                category_slug=category["slug"],
                markup_percent=markup,
                platform_name=platform["name"],
            ),
        )

    def _category_label(self, t, category: dict) -> str:
        slug = category.get("slug", "")
        if category.get("platform_slug") == "telegram":
            if slug == "members":
                return t("telegram_members")
            if slug == "views":
                return t("telegram_views")
        return category.get("name", slug)

    def _context_for_service(self, service_id: int) -> dict[str, Any] | None:
        try:
            service = self.engagement_repo.get_provider_service(service_id)
            if not service or service.get("status") != "active":
                return None
            category = self.engagement_repo.get_category(service["category_id"])
            if not category:
                return None
            platform = self.engagement_repo.get_platform_by_slug(category["platform_slug"])
            if not platform:
                return None
        except EngagementAPIError as exc:
            LOG.warning("Cannot load service context: %s", exc)
            return None

        markup = self.settings_repo.get_markup_percent()
        return {
            "service": service,
            "category": category,
            "platform": platform,
            "markup": markup,
            "sale_price": sale_price_per_1000(service.get("rate_milli", 0), markup),
        }

    def _start_engagement_order(self, uid: int, lang: str, t, service_id: int) -> None:
        context = self._context_for_service(service_id)
        if not context:
            self.tg.send_message(
                uid,
                t("tg_member_unavailable"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        category = context["category"]
        platform = context["platform"]
        if not category.get("enabled", True) or category.get("coming_soon", False):
            self.tg.send_message(
                uid,
                t("engagement_updating"),
                build_back_keyboard(t, t("back_to_platform", platform=platform["name"]), f"engagement:platform:{platform['slug']}"),
            )
            return

        service = context["service"]
        link_prompt = (
            t("tg_member_enter_link")
            if platform["slug"] == "telegram"
            else t("engagement_generic_link_prompt")
        )
        self.state_manager.set_state(uid, States.ENGAGEMENT_LINK, expires_in=600, **context)
        self.tg.send_message(
            uid,
            t(
                "engagement_package_details",
                service_name=html.escape(service.get("name", "Service")),
                price=context["sale_price"],
                min_qty=service.get("min_quantity", 1),
                max_qty=service.get("max_quantity", 0),
                link_prompt=link_prompt,
            ),
            build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
        )

    def _normalize_pending_context(self, uid: int, data: dict[str, Any]) -> dict[str, Any] | None:
        if "service" in data and "category" in data and "platform" in data:
            return data
        service_id = data.get("svc_id", data.get("service_id"))
        try:
            service_id = int(service_id)
        except (TypeError, ValueError):
            return None
        context = self._context_for_service(service_id)
        if not context:
            return None
        if data.get("link"):
            context["link"] = data["link"]
        return context

    def _handle_engagement_link(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        context = self._normalize_pending_context(uid, state.data)
        if not context:
            self.state_manager.clear_state(uid)
            self.tg.send_message(
                uid,
                t("tg_member_unavailable"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        platform = context["platform"]
        link = text.strip()
        if platform["slug"] == "telegram":
            valid = bool(TELEGRAM_LINK_RE.match(link))
        else:
            valid = link.startswith("http://") or link.startswith("https://")
        if not valid:
            message = t("tg_member_invalid_link") if platform["slug"] == "telegram" else t("engagement_invalid_link")
            self.tg.send_message(
                uid,
                message,
                build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
            )
            return

        service = context["service"]
        self.state_manager.set_state(
            uid,
            States.ENGAGEMENT_QTY,
            expires_in=600,
            **{**context, "link": link},
        )
        self.tg.send_message(
            uid,
            t(
                "tg_member_enter_qty",
                min_qty=service.get("min_quantity", 1),
                max_qty=service.get("max_quantity", 0),
            ),
            build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
        )

    def _handle_engagement_qty(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        context = self._normalize_pending_context(uid, state.data)
        if not context:
            self.state_manager.clear_state(uid)
            self.tg.send_message(
                uid,
                t("tg_member_unavailable"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        service = context["service"]
        platform = context["platform"]
        min_qty = int(service.get("min_quantity", 1))
        max_qty = int(service.get("max_quantity", 0))
        try:
            quantity = int(text.strip())
        except ValueError:
            self.tg.send_message(
                uid,
                t("tg_member_qty_invalid_format", min_qty=min_qty, max_qty=max_qty),
                build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
            )
            return

        if quantity <= 0:
            message = t("tg_member_qty_zero", service_name=service.get("name", ""), min_qty=min_qty, max_qty=max_qty)
        elif quantity < min_qty:
            message = t(
                "tg_member_qty_below_min",
                service_name=service.get("name", ""),
                quantity=quantity,
                min_qty=min_qty,
                max_qty=max_qty,
            )
        elif quantity > max_qty:
            message = t(
                "tg_member_qty_above_max",
                service_name=service.get("name", ""),
                quantity=quantity,
                min_qty=min_qty,
                max_qty=max_qty,
            )
        else:
            message = None

        if message:
            self.tg.send_message(
                uid,
                message,
                build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
            )
            return

        link = context.get("link", "")
        if not link:
            self.state_manager.clear_state(uid)
            self.tg.send_message(uid, t("engagement_invalid_link"), build_cancel_keyboard(t, "tools:engagement"))
            return

        total = int(context["sale_price"]) * quantity // 1000
        if total <= 0:
            self.tg.send_message(
                uid,
                t("tg_member_qty_invalid_format", min_qty=min_qty, max_qty=max_qty),
                build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
            )
            return

        request_key = f"eng:{uid}:{secrets.token_hex(12)}"
        confirm_context = {
            **context,
            "quantity": quantity,
            "total": total,
            "request_key": request_key,
        }
        self.state_manager.set_state(uid, States.ENGAGEMENT_CONFIRM, expires_in=300, **confirm_context)
        self.tg.send_message(
            uid,
            t(
                "engagement_confirm_summary",
                service_name=html.escape(service.get("name", "Service")),
                link=html.escape(link),
                quantity=quantity,
                total=total,
            ),
            build_confirm_keyboard(t, "engagement:confirm", f"engagement:platform:{platform['slug']}"),
        )

    def _normalize_confirm_context(self, uid: int, data: dict[str, Any], legacy_callback: str | None) -> dict[str, Any] | None:
        if "service" in data and "quantity" in data and "total" in data:
            return data

        # Legacy tg_member_confirm_pay:<service>:<link>:<quantity>
        if legacy_callback and legacy_callback.startswith("tg_member_confirm_pay:"):
            parts = legacy_callback.split(":")
            if len(parts) >= 4:
                try:
                    service_id = int(parts[1])
                    quantity = int(parts[-1])
                    link = ":".join(parts[2:-1])
                except (TypeError, ValueError):
                    return None
                context = self._context_for_service(service_id)
                if not context:
                    return None
                total = int(context["sale_price"]) * quantity // 1000
                digest = hashlib.sha256(f"{uid}:{service_id}:{link}:{quantity}".encode()).hexdigest()[:32]
                return {
                    **context,
                    "link": link,
                    "quantity": quantity,
                    "total": total,
                    "request_key": f"legacy:{digest}",
                }

        # Legacy in-flight state from the previous Bot Core version.
        service_id = data.get("service_id", data.get("svc_id"))
        quantity = data.get("quantity")
        link = data.get("link")
        if service_id is not None and quantity is not None and link:
            try:
                service_id = int(service_id)
                quantity = int(quantity)
            except (TypeError, ValueError):
                return None
            context = self._context_for_service(service_id)
            if not context:
                return None
            total = int(data.get("total") or int(context["sale_price"]) * quantity // 1000)
            nonce = data.get("nonce") or hashlib.sha256(f"{uid}:{service_id}:{link}:{quantity}".encode()).hexdigest()[:32]
            return {
                **context,
                "link": link,
                "quantity": quantity,
                "total": total,
                "request_key": f"legacy:{nonce}",
            }
        return None

    def _confirm_engagement_order(self, uid: int, lang: str, t, legacy_callback: str | None) -> None:
        try:
            state = self.state_manager.get_state(uid)
        except Exception:
            LOG.exception("Cannot read order state uid=%s", uid)
            self.tg.send_message(uid, t("tg_member_db_busy"))
            return

        data: dict[str, Any] = {}
        if state.name in (States.ENGAGEMENT_CONFIRM, States.TG_MEMBER_CONFIRM):
            data = state.data
            try:
                claimed = self.state_manager.claim_state(uid, state.name)
            except Exception:
                LOG.exception("Cannot claim order state uid=%s", uid)
                self.tg.send_message(uid, t("tg_member_db_busy"))
                return
            if not claimed:
                self.tg.send_message(
                    uid,
                    t("tg_member_duplicate"),
                    build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
                )
                return
        elif legacy_callback is None:
            # The confirmation was already consumed (double click) or expired.
            self.tg.send_message(
                uid,
                t("tg_member_duplicate"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        context = self._normalize_confirm_context(uid, data, legacy_callback)
        if not context:
            self.tg.send_message(
                uid,
                "Phiên đặt hàng không hợp lệ.",
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        self._place_engagement_order(uid, lang, t, context)

    def _place_engagement_order(self, uid: int, lang: str, t, data: dict[str, Any]) -> None:
        try:
            service = data["service"]
            platform = data["platform"]
            quantity = int(data["quantity"])
            link = str(data["link"])
            total = int(data["total"])
            sale_price = int(data["sale_price"])
            markup = int(data.get("markup", 0))
            request_key = str(data["request_key"])
            min_qty = int(service.get("min_quantity", 1))
            max_qty = int(service.get("max_quantity", 0))
        except (KeyError, TypeError, ValueError):
            self.tg.send_message(
                uid,
                "Phiên đặt hàng không hợp lệ.",
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        if total <= 0 or quantity <= 0 or not link or quantity < min_qty or quantity > max_qty:
            self.tg.send_message(
                uid,
                t("tg_member_unavailable"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        try:
            local_service = self.services_repo.get_or_create_engagement_service(
                name=service.get("name", "Engagement service"),
                provider_id=service.get("provider_id", "unknown"),
                provider_service_id=service.get("provider_service_id", ""),
            )
        except Exception:
            LOG.exception("Cannot create local engagement service label uid=%s", uid)
            self.tg.send_message(uid, t("tg_member_db_busy"))
            return

        try:
            outcome, order = self.order_repo.begin_provider_order(
                user_id=uid,
                service_id=local_service["id"],
                request_key=request_key,
                subject=link,
                evidence=f"engagement:{service.get('provider_id')}:{service.get('provider_service_id')};qty={quantity}",
                amount=total,
            )
        except Exception:
            # The COMMIT may have succeeded even though the response was lost.
            # Never call the provider after an ambiguous local write: that could
            # create a second provider order for the same request key.
            LOG.exception("Lost response while creating order uid=%s", uid)
            try:
                order = self.order_repo.find_by_request_key(request_key)
            except Exception:
                order = None
            if order is None:
                self._notify_admins(
                    f"⚠️ Lỗi tạo đơn nội bộ cho user <code>{uid}</code>. Chưa gọi provider. Kiểm tra log."
                )
                self.tg.send_message(uid, t("tg_member_db_busy"))
                return

            try:
                existing_provider_order = self.order_repo.get_provider_order(order["id"])
            except Exception:
                existing_provider_order = None
            if existing_provider_order:
                self.tg.send_message(
                    uid,
                    t("tg_member_duplicate"),
                    build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
                )
                return

            self._hold_for_reconciliation(
                uid,
                t,
                order,
                data,
                OrderResult(
                    success=False,
                    error="Local order write outcome unknown; provider was not called",
                    definitive=False,
                    status="pending_reconciliation",
                    reconciliation_required=True,
                ),
                "Local order write outcome unknown; provider was not called",
            )
            return

        if outcome == "duplicate":
            # A replay normally has a provider order already attached.  If it
            # does not, the first attempt may have committed the debit without
            # reaching the provider; keep the charge and reconcile manually.
            if order and order["status"] == "processing":
                try:
                    existing_provider_order = self.order_repo.get_provider_order(order["id"])
                except Exception:
                    existing_provider_order = None
                if not existing_provider_order:
                    self._hold_for_reconciliation(
                        uid,
                        t,
                        order,
                        data,
                        OrderResult(
                            success=False,
                            error="Duplicate request before provider confirmation",
                            definitive=False,
                            status="pending_reconciliation",
                            reconciliation_required=True,
                        ),
                        "Duplicate request before provider confirmation",
                    )
                    return
            self.tg.send_message(
                uid,
                t("tg_member_duplicate"),
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return
        if outcome == "insufficient":
            balance = self.wallet_repo.get_balance(uid)
            self.tg.send_message(
                uid,
                t("tg_member_insufficient_balance", need=total, have=balance),
                build_cancel_keyboard(t, f"engagement:platform:{platform['slug']}"),
            )
            return
        if outcome != "ok" or not order:
            self.tg.send_message(
                uid,
                "Phiên đặt hàng không hợp lệ.",
                build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
            )
            return

        self.tg.send_message(uid, t("tg_member_placing"))

        try:
            result = self.engagement_client.place_order(
                OrderRequest(
                    service_id=int(service["id"]),
                    quantity=quantity,
                    link=link,
                    idempotency_key=request_key,
                )
            )
        except Exception as exc:
            LOG.exception("Unexpected Engagement API client error uid=%s", uid)
            result = OrderResult(
                success=False,
                error=str(exc),
                definitive=False,
                status="pending_reconciliation",
                reconciliation_required=True,
            )

        if not result.success:
            self._handle_provider_failure(uid, t, order, data, result)
            return

        if result.reconciliation_required or result.status == "pending_reconciliation":
            self._hold_for_reconciliation(uid, t, order, data, result, "Provider outcome is unknown")
            return

        saved = None
        for attempt in range(3):
            try:
                saved = self.order_repo.attach_provider_order(
                    order_id=order["id"],
                    provider_name=service.get("provider_id", "unknown"),
                    provider_service_id=service.get("provider_service_id", ""),
                    provider_order_id=result.provider_order_id,
                    quantity=quantity,
                    link=link,
                    unit_price_milli=sale_price,
                    markup_percent=markup,
                    api_price_per_1000_milli=int(service.get("rate_milli", 0)),
                    api_response={
                        "charge_milli": result.charge_milli,
                        "status": result.status,
                        "idempotency_key": request_key,
                    },
                )
                break
            except Exception:
                LOG.exception(
                    "Cannot persist provider order %s for local order #%s (attempt %s)",
                    result.provider_order_id,
                    order["id"],
                    attempt + 1,
                )
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))

        if saved is None:
            self._hold_for_reconciliation(
                uid,
                t,
                order,
                data,
                result,
                f"Provider accepted order {result.provider_order_id} but DB write failed",
            )
            return

        self.tg.send_message(
            uid,
            t(
                "tg_member_success",
                order_id=order["id"],
                service_name=html.escape(service.get("name", "Service")),
                link=html.escape(link),
                quantity=quantity,
                total=total,
            ),
            build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
        )

    def _handle_provider_failure(self, uid: int, t, order: dict, data: dict, result: OrderResult) -> None:
        if result.definitive:
            refunded = None
            try:
                refunded = self.order_repo.refund_provider_order(order["id"], reason=result.error or "")
            except Exception:
                LOG.exception("Refund failed for order #%s", order["id"])
                try:
                    refunded = self.order_repo.get(order["id"])
                except Exception:
                    refunded = None

            if refunded is not None and refunded["status"] == "rejected":
                self.tg.send_message(
                    uid,
                    t("tg_member_failed", error=html.escape(str(result.error or "Provider rejected")[:300])),
                    build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
                )
                self._notify_admins(
                    f"↩️ Provider từ chối đơn <b>#{order['id']}</b> của user <code>{uid}</code>. "
                    f"Đã hoàn <b>{int(order['amount']):,} VNĐ</b> đúng 1 lần."
                )
                return

            self._hold_for_reconciliation(uid, t, order, data, result, "Refund could not be confirmed")
            return

        self._hold_for_reconciliation(uid, t, order, data, result, result.error or "Provider outcome unknown")

    def _hold_for_reconciliation(self, uid: int, t, order: dict, data: dict, result: OrderResult, reason: str) -> None:
        try:
            self.order_repo.mark_pending_reconciliation(order["id"])
        except Exception:
            LOG.exception("Cannot mark order #%s pending reconciliation", order["id"])
        self.tg.send_message(
            uid,
            t("tg_member_pending_reconcile", order_id=order["id"]),
            build_back_keyboard(t, t("back_engagement"), "tools:engagement"),
        )
        self._notify_admins(
            f"⚠️ Đơn <b>#{order['id']}</b> của user <code>{uid}</code> cần đối soát.\n"
            f"Provider: {html.escape(str(data.get('service', {}).get('provider_id', '')))}\n"
            f"Số tiền: <b>{int(order['amount']):,} VNĐ</b>\n"
            f"Lý do: {html.escape(reason[:300])}\n"
            f"Provider order: {html.escape(str(result.provider_order_id or 'N/A'))}"
        )

    def _notify_admins(self, text: str) -> None:
        for admin_id in self.config.admin_ids:
            try:
                self.tg.send_message(admin_id, text)
            except Exception:
                LOG.exception("Cannot notify admin %s", admin_id)

    # ------------------------------------------------------------------
    # Deposits, support, referral, orders, language
    # ------------------------------------------------------------------

    def _start_deposit(self, uid: int, lang: str, t) -> None:
        self.state_manager.set_state(uid, States.DEPOSIT_AMOUNT, expires_in=300)
        text = "💳 <b>Nạp tiền</b>\n\nNhập số tiền muốn nạp (10.000 - 100.000.000 VNĐ):"
        self.tg.send_message(uid, text, build_cancel_keyboard(t, "wallet"))

    def _handle_deposit_amount(self, uid: int, lang: str, t, text: str, state: UserState) -> None:
        try:
            amount = int(re.sub(r"[.,\s]", "", text))
            if not (10000 <= amount <= 100000000):
                raise ValueError
        except ValueError:
            self.tg.send_message(
                uid,
                t("tg_member_qty_invalid_format", min_qty=10000, max_qty=100000000),
                build_cancel_keyboard(t, "wallet"),
            )
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
        self.tg.send_message(
            uid,
            f"<b>Thông tin chuyển khoản</b>\nNgân hàng: {html.escape(bank_name)}\n"
            f"Chủ tài khoản: {html.escape(bank_owner)}\nSTK: <code>{html.escape(bank_account)}</code>\n"
            f"Số tiền: <b>{amount:,} VNĐ</b>\n"
            f"Nội dung CK: <code>TN{dep['id']}</code>\n\n"
            "Sau khi chuyển khoản, gửi <b>ảnh chứng từ hoặc mã giao dịch</b> tại đây. "
            "Hệ thống không tự ghi có nếu chưa được đối chiếu tại ngân hàng.",
        )

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
        self.tg.send_message(
            uid,
            "💬 <b>Hỗ trợ</b>\n\nGửi tin nhắn, ảnh hoặc file mô tả vấn đề. Admin sẽ phản hồi sớm nhất.",
            build_cancel_keyboard(t, "home"),
        )

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
        text = (
            f"🤝 <b>Chương trình giới thiệu</b>\n\n"
            f"Số người giới thiệu: <b>{count}</b>\n"
            f"Link giới thiệu: <code>{link}</code>\n\n"
            f"Chia sẻ link để nhận thưởng khi bạn bè tham gia!"
        )
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_faq(self, uid: int, lang: str, t) -> None:
        text = (
            "❓ <b>FAQ</b>\n\n"
            "1. <b>Cách đặt hàng?</b> Chọn dịch vụ → Nhập link/số lượng → Xác nhận → Thanh toán từ ví.\n"
            "2. <b>Nạp tiền?</b> Vào Ví tiền → Nạp tiền → Chuyển khoản → Gửi chứng từ.\n"
            "3. <b>Hoàn tiền?</b> Tự động khi đơn bị từ chối hoặc lỗi provider xác thực.\n"
            "4. <b>Liên hệ Admin?</b> Dùng mục Hỗ trợ trên menu chính."
        )
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_changelog(self, uid: int, lang: str, t) -> None:
        text = (
            "📋 <b>Cập nhật gần đây</b>\n\n"
            "• Tách Engagement API thành service riêng\n"
            "• Hỗ trợ đa nền tảng: Telegram, YouTube, Twitter, Facebook, Instagram, Shopee\n"
            "• Cải thiện bảo mật và hiệu suất"
        )
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back"), "home"))

    def _show_orders(self, uid: int, lang: str, t) -> None:
        orders = self.order_repo.list_user_orders(uid)
        if not orders:
            text = "📋 <b>Đơn của tôi</b>\n\nChưa có đơn hàng nào."
        else:
            lines = ["📋 <b>Đơn của tôi</b>\n"]
            for order in orders:
                lines.append(
                    f"#{order['id']} | {html.escape(str(order['service_name'] or ''))} | "
                    f"{order['amount']:,} VNĐ | {order['status']}"
                )
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
        rows = []
        for service in services:
            rows.append(((f"{service['title']} - {service['price']:,} VNĐ", f"tool_buy:{service['id']}"),))
        rows.append(((t("back_tools"), "tools"),))
        self.tg.send_message(uid, t("tool_menu"), {"inline_keyboard": rows})

    def _show_tool_sub(self, uid: int, lang: str, t) -> None:
        text = t("tool_sub_title") + "\n\n" + t("tool_sub_none") + "\n\n" + t("tool_sub_note")
        self.tg.send_message(uid, text, build_back_keyboard(t, t("back_tools"), "tools"))

    def _start_report_flow(self, uid: int, lang: str, t) -> None:
        self.tg.send_message(
            uid,
            "🚧 Tính năng gửi báo cáo đang phát triển.",
            build_back_keyboard(t, t("back_tools"), "tools"),
        )

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

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
            for dep in deposits:
                text += f"#{dep['id']} | User: {dep['user_id']} | {dep['amount']:,} VNĐ | {dep['status']}\n"
            self.tg.send_message(uid, text, build_back_keyboard(t, "← Admin", "admin:panel"))
        elif data == "admin:orders":
            orders = self.order_repo.list_all_orders()
            text = "📦 <b>All Orders</b>\n\n"
            for order in orders:
                text += (
                    f"#{order['id']} | User: {order['user_id']} | "
                    f"{html.escape(str(order['service_name'] or ''))} | {order['amount']:,} VNĐ | {order['status']}\n"
                )
            self.tg.send_message(uid, text, build_back_keyboard(t, "← Admin", "admin:panel"))
        elif data == "admin:markup":
            markup = self.settings_repo.get_markup_percent()
            self.tg.send_message(uid, f"Current markup: {markup}%\nUse /markup <percent> to change.")
        elif data == "admin:stats":
            users = self.db.fetchone("SELECT COUNT(*) c FROM users")["c"]
            balance = self.db.fetchone("SELECT SUM(balance) s FROM users")["s"] or 0
            orders = self.db.fetchone("SELECT COUNT(*) c FROM orders")["c"]
            self.tg.send_message(
                uid,
                f"👥 Users: {users}\n💰 Total Balance: {balance:,} VNĐ\n📦 Orders: {orders}",
            )

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
