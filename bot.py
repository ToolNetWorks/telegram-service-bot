#!/usr/bin/env python3
"""ToolNet Service Bot -- stdlib-only, long polling, manual payment verification.

Does not automate platform reports or promise removal of third-party accounts.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import html
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from db import Database, utcnow
from i18n import LANGUAGES, translate
from vietnamfb_api import VietnamFBAPI, create_api_client, VietnamFBError, Service
STATUSES = {
    "awaiting_quote": "Chờ báo giá", "awaiting_payment": "Chờ thanh toán",
    "pending_review": "Chờ xét duyệt", "processing": "Đang xử lý",
    "pending_reconciliation": "Chờ đối soát",
    "completed": "Hoàn thành", "rejected": "Đã từ chối/hoàn tiền",
}
# Provider order statuses
PROVIDER_STATUSES = {
    "pending": "Chờ xử lý", "processing": "Đang chạy", "completed": "Hoàn thành",
    "partial": "Hoàn thành một phần", "cancelled": "Đã hủy", "failed": "Thất bại",
}
MAX_TEXT = 1200
LOG = logging.getLogger("servicebot")
BASE_DIR = Path(__file__).resolve().parent
WELCOME_GIF = BASE_DIR / "assets" / "gifs" / "welcome.gif"
TOOLS_GIF = BASE_DIR / "assets" / "gifs" / "tools.gif"
ENGAGEMENT_GIF = BASE_DIR / "assets" / "gifs" / "engagement.gif"
PLATFORMS = {"telegram": "Telegram", "tiktok": "TikTok", "youtube": "YouTube",
             "facebook": "Facebook", "instagram": "Instagram"}
# Engagement platforms (for the new menu structure)
ENGAGEMENT_PLATFORMS = [
    ("telegram", "Telegram", "📱"),
    ("youtube", "YouTube", "📺"),
    ("twitter", "Twitter (X)", "🐦"),
    ("facebook", "Facebook", "📘"),
    ("instagram", "Instagram", "📷"),
    ("shopee", "Shopee", "🛍️"),
]
TARGET_TYPES = {
    "telegram": ("profile", "channel", "group", "post"),
    "tiktok": ("profile", "post"), "youtube": ("profile", "channel", "post"),
    "facebook": ("profile", "group", "post"), "instagram": ("profile", "post"),
}
TELEGRAM_MEMBER_PACKAGES = (
    {
        "id": "1720",
        "name": "Telegram Members HQ",
        "price_milli": 40686,
        "min": 10,
        "max": 1_000_000,
        "speed": {"vi": "50–100k/ngày", "en": "50–100k/day"},
        "warranty": {"vi": "Cancel/Refill · 7 ngày", "en": "Cancel/Refill · 7 days"},
    },
    {
        "id": "1510",
        "name": "Telegram Members",
        "price_milli": 47664,
        "min": 10,
        "max": 1_000_000,
        "speed": {"vi": "30–50k/ngày", "en": "30–50k/day"},
        "warranty": {"vi": "Non-drop · +10% overflow · 7 ngày", "en": "Non-drop · +10% overflow · 7 days"},
    },
    {
        "id": "1694",
        "name": "Telegram Premium Members",
        "price_milli": 142330,
        "min": 1,
        "max": 500_000,
        "speed": {"vi": "10k/ngày", "en": "10k/day"},
        "warranty": {"vi": "Non-drop 15–20 ngày · Refill 10 ngày", "en": "Non-drop 15–20 days · Refill 10 days"},
    },
)
PLATFORM_HOSTS = {
    "telegram": ("t.me", "telegram.me"),
    "tiktok": ("tiktok.com",), "youtube": ("youtube.com", "youtu.be"),
    "facebook": ("facebook.com", "fb.watch"), "instagram": ("instagram.com",),
}


def valid_target(value: str, platform: str) -> bool:
    """Accept a public platform URL, public @handle or numeric public ID only."""
    if not 2 <= len(value) <= 500 or "\n" in value or "\r" in value:
        return False
    if re.fullmatch(r"@[A-Za-z0-9_.]{3,64}", value) or re.fullmatch(r"[0-9]{4,25}", value):
        return True
    try:
        target = urlsplit(value)
        if target.scheme != "https" or not target.hostname or target.username or target.password:
            return False
        hostname = target.hostname.lower().rstrip(".")
        return any(hostname == domain or hostname.endswith("." + domain)
                   for domain in PLATFORM_HOSTS.get(platform, ()))
    except ValueError:
        return False


def env_file(filename=".env"):
    if not Path(filename).exists():
        return
    for line in Path(filename).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def money(amount) -> str:
    return f"{int(amount):,}".replace(",", ".") + " ₫"


def localized_int(amount, language="vi") -> str:
    value = f"{int(amount):,}"
    return value if language == "en" else value.replace(",", ".")


def keyboard(*rows):
    return {"inline_keyboard": [[{"text": title, "callback_data": data} for title, data in row]
                                for row in rows]}


HOME = keyboard(
    (("Ví tiền", "wallet"),),
    (("Tool Access", "tools"),),
    (("Hỗ trợ", "support"), ("Giới thiệu", "referral")),
    (("FAQ", "faq"), ("Cập nhật", "changelog")),
    (("Đơn của tôi", "orders"),),
)
BACK = keyboard((("← Menu chính", "home"),))


class ApiError(Exception):
    pass


class Telegram:
    def __init__(self, token: str):
        self.url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **params):
        request = urllib.request.Request(
            self.url + method,
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("description", f"HTTP {exc.code}")
            except (ValueError, OSError):
                detail = f"HTTP {exc.code}"
            raise ApiError(f"Telegram {method}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or type(exc).__name__
            raise ApiError(f"Network/API error at {method}: {str(reason)[:200]}") from None
        if not body.get("ok"):
            raise ApiError(f"Telegram {method}: {body.get('description', 'unknown error')}")
        return body.get("result")

    def send(self, user_id, text, markup=None):
        data = {"chat_id": user_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if markup:
            data["reply_markup"] = markup
        return self.call("sendMessage", **data)

    def send_media(self, user_id, kind, file_id, caption, markup=None):
        method = {"photo": "sendPhoto", "animation": "sendAnimation"}.get(kind)
        if not method:
            raise ApiError("Unsupported media banner type")
        data = {"chat_id": user_id, kind: file_id, "caption": caption, "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = markup
        return self.call(method, **data)

    def call_multipart(self, method: str, params: dict, files):
        boundary = "----ToolNet" + secrets.token_hex(16)
        payload = bytearray()
        for name, value in params.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            payload.extend(f"--{boundary}\r\n".encode("utf-8"))
            payload.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            payload.extend(str(value).encode("utf-8"))
            payload.extend(b"\r\n")
        for name, filename, content_type, content in files:
            payload.extend(f"--{boundary}\r\n".encode("utf-8"))
            payload.extend(
                (f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
            )
            payload.extend(content)
            payload.extend(b"\r\n")
        payload.extend(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            self.url + method, data=bytes(payload),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("description", f"HTTP {exc.code}")
            except (ValueError, OSError):
                detail = f"HTTP {exc.code}"
            raise ApiError(f"Telegram {method}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or type(exc).__name__
            raise ApiError(f"Network/API error at {method}: {str(reason)[:200]}") from None
        if not result.get("ok"):
            raise ApiError(f"Telegram {method}: {result.get('description', 'unknown error')}")
        return result.get("result")

    def send_animation_file(self, user_id, path, caption, markup=None):
        content = Path(path).read_bytes()
        if content[:6].startswith(b"GIF8"):
            filename, content_type = "welcome.gif", "image/gif"
        else:
            filename, content_type = "welcome.mp4", "video/mp4"
        data = {"chat_id": user_id, "caption": caption[:1024], "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = markup
        return self.call_multipart("sendAnimation", data,
                                   [("animation", filename, content_type, content)])


class App:
    def __init__(self):
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or ":" not in token:
            raise ValueError("BOT_TOKEN phải lấy từ @BotFather và điền vào .env")
        self.api = Telegram(token)
        backend = os.getenv("DB_BACKEND", "").strip().lower() or None
        self.db = Database(os.getenv("DB_PATH", "./data/bot.sqlite3"), backend=backend)
        self.admins = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
        if not self.admins:
            raise ValueError("ADMIN_IDS chưa thiết lập; bot yêu cầu ít nhất một Admin")
        self.name = os.getenv("BOT_NAME", "ToolNet Services")[:48]
        self.support = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
        self.bank_name = os.getenv("BANK_NAME", "").strip()
        self.bank_account = os.getenv("BANK_ACCOUNT", "").strip()
        self.bank_owner = os.getenv("BANK_OWNER", "").strip()
        # VietnamFB API client
        try:
            self.provider = create_api_client()
        except Exception as e:
            LOG.warning("VietnamFB API client not initialized: %s", e)
            self.provider = None
        self.username = ""
        self.offset = int(self.db.get_setting("poll_offset") or "0")
        self.running = True

    def is_admin(self, uid):
        return uid in self.admins

    def deliver(self, uid, text, markup=None):
        try:
            self.api.send(uid, text, markup)
            return True
        except ApiError as exc:
            LOG.warning("Không gửi được tin đến %s: %s", uid, exc)
            return False

    def admins_notify(self, text, media=None):
        for uid in self.admins:
            self.deliver(uid, text)
            if media:
                kind, file_id = media
                try:
                    method = {"photo": "sendPhoto", "document": "sendDocument", "video": "sendVideo"}.get(kind)
                    if method:
                        self.api.call(method, chat_id=uid, **{kind: file_id})
                except ApiError as exc:
                    LOG.warning("Không gửi được file bằng chứng: %s", exc)

    def lang(self, uid):
        user = self.db.get_user(uid)
        return (user["language"] if user and user["language"] in LANGUAGES else "en")

    def t(self, uid, key, **params):
        return translate(self.lang(uid), key, **params)

    def back(self, uid):
        return keyboard(((self.t(uid, "back"), "home"),))

    def home_keyboard(self, uid):
        return keyboard(
            ((self.t(uid, "wallet"), "wallet"),),
            ((self.t(uid, "tools"), "tools"),),
            ((self.t(uid, "support"), "support"), (self.t(uid, "referral"), "referral")),
            ((self.t(uid, "faq"), "faq"), (self.t(uid, "changes"), "changelog")),
            ((self.t(uid, "orders"), "orders"), (self.t(uid, "language"), "language")),
        )

    def tools_menu(self, uid):
        text = self.t(uid, "tool_menu")
        markup = keyboard(
            ((self.t(uid, "report"), "tools:report"), (self.t(uid, "engagement"), "tools:engagement")),
            ((self.t(uid, "tool_buy"), "tools:buy"), (self.t(uid, "tool_sub"), "tools:sub")),
            ((self.t(uid, "tool_back_main"), "home"),),
        )
        if self.send_default_animation(uid, text, markup, image_name="tools"):
            return
        self.deliver(uid, text, markup)

    def engagement_menu(self, uid):
        """Display engagement platforms in a 2-column grid."""
        text = self.t(uid, "engagement_menu")
        language = self.lang(uid)
        
        # Build 2-column keyboard from ENGAGEMENT_PLATFORMS
        rows = []
        for i in range(0, len(ENGAGEMENT_PLATFORMS), 2):
            row = []
            slug1, name1, icon1 = ENGAGEMENT_PLATFORMS[i]
            # Check if platform is enabled in database
            platform1 = self.db.get_engagement_platform_by_slug(slug1)
            if platform1 and platform1["enabled"]:
                label1 = f"{icon1} {self.t(uid, f'engagement_{slug1}')}"
                row.append((label1, f"engagement:platform:{slug1}"))
            else:
                label1 = f"{icon1} {self.t(uid, f'engagement_{slug1}')} {self.t(uid, 'engagement_coming_soon')}"
                row.append((label1, f"engagement:coming_soon:{slug1}"))
            
            if i + 1 < len(ENGAGEMENT_PLATFORMS):
                slug2, name2, icon2 = ENGAGEMENT_PLATFORMS[i + 1]
                platform2 = self.db.get_engagement_platform_by_slug(slug2)
                if platform2 and platform2["enabled"]:
                    label2 = f"{icon2} {self.t(uid, f'engagement_{slug2}')}"
                    row.append((label2, f"engagement:platform:{slug2}"))
                else:
                    label2 = f"{icon2} {self.t(uid, f'engagement_{slug2}')} {self.t(uid, 'engagement_coming_soon')}"
                    row.append((label2, f"engagement:coming_soon:{slug2}"))
            rows.append(tuple(row))
        
        # Back button
        rows.append(((self.t(uid, "back_tools"), "tools"),))
        
        markup = keyboard(*rows)
        if self.send_default_animation(uid, text, markup, image_name="engagement"):
            return
        self.deliver(uid, text, markup)

    def engagement_platform(self, uid, platform_slug: str):
        """Display service categories for a platform."""
        platform = self.db.get_engagement_platform_by_slug(platform_slug)
        if not platform:
            return self.deliver(uid, "Platform not found.", keyboard(((self.t(uid, "back_tools"), "tools"),)))
        
        if not platform["enabled"]:
            return self.deliver(uid, self.t(uid, "engagement_coming_soon"), 
                                keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))
        
        categories = self.db.list_engagement_categories(platform["id"])
        if not categories:
            return self.deliver(uid, self.t(uid, "engagement_no_services"),
                                keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))
        
        text = self.t(uid, "engagement_select_category")
        rows = []
        for i in range(0, len(categories), 2):
            row = []
            cat1 = categories[i]
            label1 = self.t(uid, f'{cat1["slug"]}') if cat1["slug"] in ("members", "views") else cat1["name"]
            # Use translation key if available
            if cat1["slug"] == "members":
                label1 = self.t(uid, "telegram_members")
            elif cat1["slug"] == "views":
                label1 = self.t(uid, "telegram_views")
            row.append((label1, f"engagement:category:{cat1['id']}"))
            
            if i + 1 < len(categories):
                cat2 = categories[i + 1]
                label2 = self.t(uid, f'{cat2["slug"]}') if cat2["slug"] in ("members", "views") else cat2["name"]
                if cat2["slug"] == "members":
                    label2 = self.t(uid, "telegram_members")
                elif cat2["slug"] == "views":
                    label2 = self.t(uid, "telegram_views")
                row.append((label2, f"engagement:category:{cat2['id']}"))
            rows.append(tuple(row))
        
        rows.append(((self.t(uid, "back_engagement"), "tools:engagement"),))
        self.deliver(uid, text, keyboard(*rows))

    def telegram_members(self, uid):
        """Show Telegram Member packages from provider API (existing functionality)."""
        if not self.provider:
            return self.deliver(uid, "Provider API not configured.", self.back(uid))
        try:
            services = self.provider.get_telegram_member_services()
        except VietnamFBError as e:
            LOG.error("Failed to fetch Telegram member services: %s", e)
            return self.deliver(uid, self.t(uid, "tg_member_api_error", error=str(e)), self.back(uid))

        if not services:
            return self.deliver(uid, self.t(uid, "no_services"), keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))

        language = self.lang(uid)
        text = self.t(uid, "tg_member_select") + "\n\n"
        rows = []
        # Clean display names mapping
        display_names = {
            "1720": "Telegram Members HQ | Speed: ♻️",
            "1510": "Telegram Members PLUS | Speed",
            "1694": "Telegram - Premium Members",
        }
        for index, svc in enumerate(services):
            # API price is per 1000 units (VND)
            api_price_per_1000 = svc.price_per_1000
            markup_percent = self.db.get_markup_percent()
            # Selling price = API price * (1 + markup/100)
            selling_price_per_1000 = (api_price_per_1000 * Decimal(100 + markup_percent) / Decimal(100)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )

            # Format price for display
            if language == "en":
                unit_price_str = f"{selling_price_per_1000:,.3f}".replace(",", " ")
            else:
                unit_price_str = f"{selling_price_per_1000:,.3f}".replace(",", " ").replace(".", ",")

            # Clean display name
            display_name = display_names.get(svc.service_id, esc(svc.name))
            refill_indicator = " ♻️" if svc.refill else ""

            text += (
                f"<b>{index}. {display_name}</b> <code>#{svc.service_id}</code>\n"
                f"{self.t(uid, 'member_price')}: <b>{unit_price_str} {self.t(uid, 'member_unit')}</b>\n"
                f"{self.t(uid, 'member_min')}: {localized_int(svc.min_quantity, language)} · "
                f"{self.t(uid, 'member_max')}: {localized_int(svc.max_quantity, language)}\n"
                f"{self.t(uid, 'member_speed')}: {esc(svc.average_time) or 'N/A'} · "
                f"{self.t(uid, 'member_warranty')}: {'Refill' if svc.refill else 'No refill'}{refill_indicator}\n\n"
            )
            rows.append(((f"{index}. {display_name[:30]}", f"tg_member_select:{svc.service_id}"),))

        text += self.t(uid, "member_note")
        # Arrange in 2 columns if possible
        markup_rows = []
        for i in range(0, len(rows), 2):
            if i + 1 < len(rows):
                markup_rows.append((rows[i][0], rows[i+1][0]))
            else:
                markup_rows.append(rows[i])
        markup_rows.append(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),))
        self.deliver(uid, text, keyboard(*markup_rows))

    def telegram_views(self, uid):
        """Show Telegram Views services. Currently unavailable - placeholder."""
        # Check if there are any provider services for views category
        platform = self.db.get_engagement_platform_by_slug("telegram")
        if not platform:
            return self.deliver(uid, self.t(uid, "telegram_views_unavailable"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        
        views_category = self.db.get_engagement_category_by_slug(platform["id"], "views")
        if not views_category or not views_category["enabled"]:
            return self.deliver(uid, self.t(uid, "telegram_views_unavailable"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        
        # Check if there are active provider services
        provider_services = self.db.list_engagement_provider_services(views_category["id"])
        if not provider_services:
            return self.deliver(uid, self.t(uid, "telegram_views_no_provider"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        
        # TODO: Implement views ordering flow when provider services are available
        # For now, show unavailable message
        self.deliver(uid, self.t(uid, "telegram_views_unavailable"),
                     keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))

    def tg_member_start_order(self, uid, service_id):
        """Bắt đầu quy trình đặt hàng: nhập link group."""
        svc = self.provider.get_service(service_id)
        if not svc:
            return self.deliver(uid, "Dịch vụ không tồn tại.", keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        self.db.set_state(uid, "tg_member_link", service_id=service_id, min_qty=svc.min_quantity, max_qty=svc.max_quantity)
        self.deliver(uid, self.t(uid, "tg_member_enter_link"),
                     keyboard(((self.t(uid, "cancel"), "engagement:platform:telegram"),)))

    def tg_member_confirm_pay(self, uid):
        """Xác nhận thanh toán và đặt đơn provider với các lớp chống trùng.

        Thứ tự an toàn:
          1. claim state nguyên tử (chống bấm 2 lần),
          2. tạo order nội bộ + trừ ví + ghi ledger trong CÙNG transaction,
          3. gọi provider,
          4. chỉ ghi nhận thành công khi provider trả về order id,
          5. lỗi rõ ràng -> hoàn tiền đúng 1 lần; lỗi mơ hồ -> chờ đối soát.
        """
        try:
            state, data = self.db.get_state(uid)
        except Exception:
            LOG.exception("Không đọc được trạng thái đặt đơn uid=%s", uid)
            return self.deliver(uid, self.t(uid, "tg_member_db_busy"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        if state != "tg_member_confirm" or "service_id" not in data:
            return self.deliver(uid, "Phiên đặt hàng không hợp lệ.",
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        try:
            claimed = self.db.claim_state(uid, "tg_member_confirm")
        except Exception:
            LOG.exception("Không claim được state đặt đơn uid=%s", uid)
            return self.deliver(uid, self.t(uid, "tg_member_db_busy"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        if not claimed:
            return self.deliver(uid, self.t(uid, "tg_member_duplicate"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        try:
            self._place_tg_member_order(uid, data)
        except Exception:
            LOG.exception("Lỗi không xác định khi đặt đơn provider uid=%s", uid)
            try:
                self.db.set_state(uid, "")
            except Exception:
                LOG.exception("Không xoá được state uid=%s", uid)
            self.deliver(uid, self.t(uid, "tg_member_timeout"),
                         keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))
            self.admins_notify(f"⚠️ Lỗi hệ thống khi đặt đơn provider cho user <code>{uid}</code>. "
                               f"Kiểm tra log (không chứa token) và đối soát panel.")

    def _place_tg_member_order(self, uid, data):
        if not self.provider:
            self.db.set_state(uid, "")
            return self.deliver(uid, self.t(uid, "tg_member_unavailable"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        svc = self.provider.get_service(data.get("service_id", ""))
        tool_service = self.db.get_service_by_title("Tool Access")
        if not svc or not tool_service:
            self.db.set_state(uid, "")
            return self.deliver(uid, self.t(uid, "tg_member_unavailable"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        try:
            quantity = int(data["quantity"])
            total = int(data["total"])
            link = str(data["link"])
            unit_price_milli = int(data.get("unit_price_milli", 0))
            api_price_milli = int(data.get("api_price_milli", 0))
            markup_percent = int(data.get("markup_percent", 0))
        except (KeyError, TypeError, ValueError):
            self.db.set_state(uid, "")
            return self.deliver(uid, "Phiên đặt hàng không hợp lệ.",
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        if total <= 0 or quantity <= 0 or not link:
            self.db.set_state(uid, "")
            return self.deliver(uid, "Phiên đặt hàng không hợp lệ.",
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))

        request_key = f"tgprov:{data.get('nonce') or secrets.token_hex(8)}"
        try:
            outcome, order = self.db.begin_provider_order(
                user_id=uid,
                service_id=tool_service["id"],
                request_key=request_key,
                subject=f"vietnamfb:{svc.service_id}",
                evidence=f"link={link};qty={quantity}",
                amount=total,
            )
        except Exception:
            # The COMMIT response may have been lost.  The unique request_key
            # lets us recover the order instead of debiting twice on retry.
            LOG.exception("Lỗi tạo order nội bộ uid=%s; kiểm tra request_key", uid)
            try:
                recovered = self.db.one("SELECT * FROM orders WHERE request_key=?",
                                        (request_key,))
            except Exception:
                recovered = None
            if recovered is None:
                raise
            outcome, order = "ok", recovered
        if outcome == "duplicate":
            return self.deliver(uid, self.t(uid, "tg_member_duplicate"),
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        if outcome == "insufficient":
            balance = self.db.get_user(uid)["balance"]
            return self.deliver(uid, self.t(uid, "tg_member_insufficient_balance",
                                               need=total, have=balance),
                                keyboard(((self.t(uid, "cancel"), "engagement:platform:telegram"),)))
        if outcome != "ok" or not order:
            self.db.set_state(uid, "")
            return self.deliver(uid, "Phiên đặt hàng không hợp lệ.",
                                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))

        self.deliver(uid, self.t(uid, "tg_member_placing"))

        try:
            result = self.provider.add_order(
                service_id=svc.service_id,
                link=link,
                quantity=quantity,
            )
        except VietnamFBError as exc:
            self._handle_provider_failure(uid, order, data, svc, exc)
            return
        except Exception as exc:
            LOG.exception("Lỗi không xác định từ provider uid=%s order=%s", uid, order["id"])
            self._handle_provider_failure(uid, order, data, svc,
                                          VietnamFBError(f"Unexpected: {exc}", definitive=False))
            return

        provider_order_id = str(getattr(result, "order_id", "") or "")
        if not provider_order_id:
            self._handle_provider_failure(
                uid, order, data, svc,
                VietnamFBError("Provider không trả về order id", definitive=False))
            return

        saved = None
        for attempt in range(3):
            try:
                saved = self.db.attach_provider_order(
                    order_id=order["id"],
                    provider_name="vietnamfb",
                    provider_service_id=svc.service_id,
                    provider_order_id=provider_order_id,
                    quantity=quantity,
                    link=link,
                    unit_price_milli=unit_price_milli,
                    markup_percent=markup_percent,
                    api_price_per_1000_milli=api_price_milli,
                    api_response={"order": provider_order_id,
                                  "status": getattr(result, "status", "")},
                )
                break
            except Exception:
                LOG.exception("Chưa lưu được provider order %s (lần %s) cho order #%s",
                              provider_order_id, attempt + 1, order["id"])
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))

        if saved is not None:
            self.db.set_state(uid, "")
            self.deliver(uid, self.t(uid, "tg_member_success",
                order_id=order["id"],
                service_name=svc.name,
                link=link,
                quantity=quantity,
                total=total),
                keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
            return

        # Provider already accepted the order but the DB write failed: never
        # refund blindly. Keep the debit and alert admins for reconciliation.
        self._provider_pending(
            uid, order, data, svc,
            f"Provider đã nhận đơn {provider_order_id} nhưng chưa lưu được vào DB",
        )

    def _handle_provider_failure(self, uid, order, data, svc, exc):
        if getattr(exc, "definitive", False):
            try:
                refunded = self.db.reject_order(order["id"])
            except Exception:
                LOG.exception("Không hoàn được tiền cho order #%s", order["id"])
                try:
                    refreshed = self.db.get_order(order["id"])
                except Exception:
                    refreshed = None
                if refreshed is not None and refreshed["status"] == "rejected":
                    refunded = refreshed
                else:
                    self._provider_pending(uid, order, data, svc,
                                           f"Lỗi hoàn tiền sau khi provider từ chối: {exc}")
                    return
            try:
                self.db.set_state(uid, "")
            except Exception:
                LOG.exception("Không xoá được state uid=%s", uid)
            if refunded is not None:
                self.deliver(uid, self.t(uid, "tg_member_failed", error=esc(str(exc))[:300]),
                             keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
                self.admins_notify(
                    f"Đơn provider <b>#{order['id']}</b> bị từ chối, đã hoàn "
                    f"<b>{money(int(order['amount']))}</b> cho user <code>{uid}</code>.\n"
                    f"Lý do: {esc(str(exc))[:300]}"
                )
            else:
                self.deliver(uid, self.t(uid, "tg_member_duplicate"),
                             keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
            return
        self._provider_pending(uid, order, data, svc, str(exc))

    def _provider_pending(self, uid, order, data, svc, reason):
        """Provider result ambiguous: keep debit, flag reconciliation, alert admin."""
        try:
            self.db.mark_order_pending_reconciliation(order["id"])
        except Exception:
            LOG.exception("Không đánh dấu được order #%s là chờ đối soát", order["id"])
        try:
            self.db.set_state(uid, "")
        except Exception:
            LOG.exception("Không xoá được state uid=%s", uid)
        self.deliver(uid, self.t(uid, "tg_member_pending_reconcile", order_id=order["id"]),
                     keyboard(((self.t(uid, "back_telegram"), "engagement:platform:telegram"),)))
        link = str(data.get("link", ""))
        quantity = data.get("quantity", 0)
        self.admins_notify(
            f"⚠️ <b>Đơn cần đối soát</b>\n"
            f"Mã nội bộ: <b>#{order['id']}</b>\n"
            f"User: <code>{uid}</code>\n"
            f"Dịch vụ: {esc(svc.name)} (#{esc(svc.service_id)})\n"
            f"Link: {esc(link)}\n"
            f"Số lượng: {quantity}\n"
            f"Đã trừ: <b>{money(int(order['amount']))}</b>\n"
            f"Lý do: {esc(str(reason))[:300]}\n"
            f"Kiểm tra panel provider. Nếu provider chưa nhận đơn, hoàn tiền bằng /reject {order['id']}."
        )

    def tool_subscription(self, uid):
        records = self.db.list_tool_orders(uid)
        text = self.t(uid, "tool_sub_title") + "\n\n"
        if records:
            text += "\n".join(
                f"#{r['id']} · {STATUSES.get(r['status'], r['status'])} · "
                f"{money(r['amount']) if r['amount'] else self.t(uid, 'price_quote')}"
                for r in records
            )
        else:
            text += self.t(uid, "tool_sub_none")
        text += "\n\n" + self.t(uid, "tool_sub_note")
        self.deliver(uid, text, keyboard(
            ((self.t(uid, "tool_buy"), "tools:buy"),),
            ((self.t(uid, "back_tools"), "tools"),),
        ))

    def choose_language(self, uid, first_time=False):
        rows = [((label, f"lang:{code}"),) for code, label in LANGUAGES.items()]
        message = self.t(uid, "choose_language") if first_time else self.t(uid, "language") + " / Choose your language:"
        self.deliver(uid, message, keyboard(*rows))

    def start_verification(self, uid, force=False):
        state, data = self.db.get_state(uid)
        if (not force and state == "captcha" and int(data.get("expires", 0)) > int(time.time())):
            a, b = data["a"], data["b"]
        else:
            a, b = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
            self.db.set_state(uid, "captcha", a=a, b=b, tries=0, expires=int(time.time()) + 300)
        return self.deliver(uid, translate("vi", "captcha", a=a, b=b))

    def require_onboarding(self, uid):
        user = self.db.get_user(uid)
        if not user or not user["verified_at"]:
            return self.start_verification(uid)
        if not user["language"]:
            return self.choose_language(uid)
        return None

    def send_default_animation(self, uid, text, markup, image_name="welcome"):
        """Upload and cache a default animation (GIF/MP4) from assets/gifs/.
        image_name: 'welcome' or 'tools' (without extension).
        Returns True if animation was sent, False on fallback to text.
        """
        gif_map = {"welcome": WELCOME_GIF, "tools": TOOLS_GIF, "engagement": ENGAGEMENT_GIF}
        path = gif_map.get(image_name)
        if not path or not path.is_file():
            return False
        stat = path.stat()
        signature = f"{stat.st_size}:{int(stat.st_mtime)}"
        id_key, sig_key = f"{image_name}_gif_id", f"{image_name}_gif_sig"
        if self.db.get_setting(sig_key) == signature:
            file_id = self.db.get_setting(id_key)
            if file_id:
                try:
                    self.api.send_media(uid, "animation", file_id, text[:1024], markup)
                    return True
                except ApiError as exc:
                    LOG.warning("Không gửi được %s.gif đã lưu, tải lại: %s", image_name, exc)
                    self.db.set_setting(id_key, "")
        try:
            result = self.api.send_animation_file(uid, path, text[:1024], markup)
        except ApiError as exc:
            LOG.warning("Không gửi được %s.gif, dùng tin nhắn chữ: %s", image_name, exc)
            return False
        file_id = ((result or {}).get("animation") or {}).get("file_id")
        if file_id:
            self.db.set_setting(id_key, file_id)
            self.db.set_setting(sig_key, signature)
        return True

    def send_home(self, uid, welcome=False):
        user = self.db.get_user(uid)
        greeting = esc((user["display_name"] or "friend")[:80]) if user else "friend"
        text = f"<b>{esc(self.name)}</b>\n\n" + self.t(uid, "home", name=greeting)
        markup = self.home_keyboard(uid)
        kind = self.db.get_setting("banner_kind")
        file_id = self.db.get_setting("banner_id")
        if kind and file_id:
            try:
                self.api.send_media(uid, kind, file_id, text[:1024], markup)
                return
            except ApiError as exc:
                LOG.warning("Không thể gửi ảnh/GIF giới thiệu, dùng tin nhắn chữ: %s", exc)
        if welcome and self.send_default_animation(uid, text, markup):
            return
        self.deliver(uid, text, markup)

    def wallet(self, uid):
        user = self.db.get_user(uid)
        self.deliver(uid, f"<b>Ví của bạn</b>\nSố dư: <b>{money(user['balance'])}</b>\n\n"
                          "Chỉ ghi có sau khi Admin xác minh giao dịch thực tế.",
                     keyboard((("Nạp tiền", "deposit"), ("Lịch sử nạp", "mydeposits")),
                              (("← Menu chính", "home"),)))

    def service_label(self, uid, service):
        title = service["title"]
        if self.lang(uid) == "vi":
            return title
        if title.startswith("Rà soát vi phạm "):
            return f"{title.removeprefix('Rà soát vi phạm ')} Report"
        if title == "Hỗ trợ khiếu nại":
            return "Account Appeal Support"
        return title

    def service_description(self, uid, service):
        if self.lang(uid) == "vi":
            return service["description"]
        if service["platform"] in PLATFORMS:
            return "Submit a public link and evidence of a genuine policy violation for manual review."
        if service["platform"] == "tools":
            return "Request a quote for lawful software access and maintenance."
        return "Request assistance from our support team."

    def platforms(self, uid):
        rows = [((name, f"platform:{code}"),) for code, name in PLATFORMS.items()]
        rows.extend([((self.t(uid, "back_tools"), "tools"),)])
        self.deliver(uid, self.t(uid, "choose_platform"), keyboard(*rows))

    def services(self, uid, tool_only=False, platform=None):
        if not tool_only and not platform:
            return self.platforms(uid)
        selected = "tools" if tool_only else platform
        if selected not in (*PLATFORMS, "tools"):
            return self.deliver(uid, self.t(uid, "no_services"), self.back(uid))
        rows = []
        for service in self.db.list_services(selected):
            title = self.service_label(uid, service)
            label = f"{title} · {money(service['price'])}" if service["price"] else title
            rows.append(((label[:62], f"service:{service['id']}"),))
        if tool_only:
            rows.append(((self.t(uid, "back_tools"), "tools"),))
        else:
            rows.append(((self.t(uid, "back_platforms"), "services"),))
        self.deliver(uid, self.t(uid, "choose_service") if len(rows) > 1 else self.t(uid, "no_services"),
                     keyboard(*rows))

    def service_detail(self, uid, service_id):
        service = self.db.get_service(service_id)
        if not service:
            return self.deliver(uid, "Service is unavailable.", self.back(uid))
        price = money(service["price"]) if service["price"] else self.t(uid, "price_quote")
        if service["platform"] in PLATFORMS:
            back_action = f"platform:{service['platform']}"
            back_label = self.t(uid, "back_platforms")
        elif service["platform"] == "tools":
            back_action = "tools:buy"
            back_label = self.t(uid, "back_tools")
        else:
            back_action = "services"
            back_label = self.t(uid, "back_platforms")
        self.deliver(uid, f"<b>{esc(self.service_label(uid, service))}</b>\n\n"
                          f"{esc(self.service_description(uid, service))}\n\n"
                          f"<b>{self.t(uid, 'cost')}:</b> {price}\n\n"
                          "Requests must concern genuine policy violations with supporting evidence.",
                     keyboard(((self.t(uid, "create"), f"new:{service_id}"),),
                              ((back_label, back_action),)))

    def choose_target(self, uid, service_id):
        service = self.db.get_service(service_id)
        if not service or service["platform"] not in TARGET_TYPES:
            return self.deliver(uid, "Service is unavailable.", self.back(uid))
        rows = [((self.t(uid, kind), f"target:{service_id}:{kind}"),)
                for kind in TARGET_TYPES[service["platform"]]]
        rows.append(((self.t(uid, "back_platforms"), f"platform:{service['platform']}"),))
        self.deliver(uid, self.t(uid, "choose_target"), keyboard(*rows))

    def orders(self, uid):
        records = self.db.list_orders(uid)
        if not records:
            return self.deliver(uid, "Bạn chưa có yêu cầu nào.", BACK)
        rows = [((f"#{r['id']} · {STATUSES.get(r['status'], r['status'])}", f"order:{r['id']}"),)
                for r in records]
        rows.append((("← Menu chính", "home"),))
        self.deliver(uid, "<b>10 yêu cầu mới nhất</b>", keyboard(*rows))

    def order_detail(self, uid, oid):
        o = self.db.get_order(oid)
        if not o or (o["user_id"] != uid and not self.is_admin(uid)):
            return self.deliver(uid, "Không tìm thấy đơn hàng.")
        text = (f"<b>Yêu cầu #{o['id']}</b>\nDịch vụ: {esc(o['service_name'])}\n"
                f"Nội dung: {esc(o['subject'])}\n"
                f"Trạng thái: <b>{esc(STATUSES.get(o['status'], o['status']))}</b>\n"
                f"Chi phí: <b>{money(o['amount']) if o['amount'] else 'Chờ báo giá'}</b>")
        markup = keyboard((("Thanh toán từ ví", f"pay:{oid}"),), (("← Đơn của tôi", "orders"),)) \
            if o["status"] == "awaiting_payment" else keyboard((("← Đơn của tôi", "orders"),))
        self.deliver(uid, text, markup)

    def faq(self, uid):
        self.deliver(uid, "<b>Câu hỏi thường gặp</b>\n\n"
                     "• Đặt yêu cầu: vào Tool Access → Send Report, mô tả đường dẫn và bằng chứng.\n"
                     "• Thanh toán: chỉ thanh toán sau khi có giá rõ ràng.\n"
                     "• Nạp ví: chuyển khoản theo mã đơn, gửi chứng từ, chờ Admin kiểm tra.\n"
                     "• Từ chối yêu cầu đã trả tiền: hoàn về ví.\n"
                     "• Dịch vụ có bảo đảm gỡ nội dung không? Không. Kết quả do nền tảng quyết định.", BACK)

    def referral(self, uid):
        link = f"https://t.me/{self.username}?start=ref_{uid}"
        self.deliver(uid, f"<b>Giới thiệu bạn bè</b>\nLink: {esc(link)}\n"
                          f"Đã giới thiệu: {self.db.referrals(uid)} người\n\n"
                          "Hiện chưa áp dụng hoa hồng tự động.", BACK)

    def bank_configured(self):
        return all([self.bank_name, self.bank_account, self.bank_owner])

    def my_deposits(self, uid):
        records = self.db.list_user_deposits(uid)
        if not records:
            return self.deliver(uid, "Chưa có yêu cầu nạp nào.", BACK)
        rows = [f"#{r['id']} · {money(r['amount'])} · {esc(r['status'])}" for r in records]
        self.deliver(uid, "<b>10 yêu cầu nạp mới nhất</b>\n" + "\n".join(rows) +
                     "\n\nNếu còn chờ chứng từ, dùng /proof MÃ_ĐƠN MÃ_GIAO_DỊCH "
                     "hoặc /canceldeposit MÃ_ĐƠN để hủy.", BACK)

    def begin_deposit(self, uid):
        if not self.bank_configured():
            return self.deliver(uid, "Chưa cấu hình thông tin nhận chuyển khoản. Hãy liên hệ hỗ trợ.", BACK)
        self.db.set_state(uid, "deposit_amount")
        self.deliver(uid, "Nhập số tiền nạp (VND), từ 10.000 đến 100.000.000.\nVí dụ: <code>200000</code>\n/cancel để hủy.")

    def begin_order(self, uid, sid, target_kind=None):
        service = self.db.get_service(sid)
        if not service:
            return self.deliver(uid, "Service is unavailable.")
        if self.db.count_active_orders(uid) >= 5:
            return self.deliver(uid, "Maximum five open cases per account.")
        if service["platform"] in TARGET_TYPES:
            if target_kind is None:
                return self.choose_target(uid, sid)
            if target_kind not in TARGET_TYPES[service["platform"]]:
                return self.deliver(uid, "Invalid target type.")
            self.db.set_state(uid, "order_target", sid=sid, nonce=secrets.token_hex(12),
                              platform=service["platform"], target_kind=target_kind)
            return self.deliver(uid, f"<b>{esc(PLATFORMS[service['platform']])} · "
                                f"{esc(self.t(uid, target_kind))}</b>\n\n{self.t(uid, 'send_target')}")
        self.db.set_state(uid, "order_subject", sid=sid, nonce=secrets.token_hex(12))
        self.deliver(uid, "Describe your requested service (10–1,200 characters). "
                          "Never send passwords, session tokens or OTPs. /cancel to exit.")

    @staticmethod
    def proof(message):
        if message.get("photo"):
            return "photo", message["photo"][-1]["file_id"]
        if message.get("document"):
            return "document", message["document"]["file_id"]
        if message.get("video"):
            return "video", message["video"]["file_id"]
        txt = (message.get("text") or message.get("caption") or "").strip()
        return ("text", txt[:MAX_TEXT]) if txt else ("", "")

    def process_state(self, uid, message, state, data):
        value = (message.get("text") or "").strip()
        if state == "captcha":
            if time.time() >= int(data.get("expires", 0)):
                self.deliver(uid, self.t(uid, "captcha_expired"))
                return self.start_verification(uid, force=True)
            if value == str(int(data["a"]) + int(data["b"])):
                self.db.verify_user(uid)
                self.deliver(uid, self.t(uid, "verified"))
                return self.choose_language(uid, first_time=True)
            remaining = 3 - int(data.get("tries", 0)) - 1
            if remaining <= 0:
                self.deliver(uid, self.t(uid, "captcha_expired"))
                return self.start_verification(uid, force=True)
            self.db.set_state(uid, "captcha", **{**data, "tries": 3 - remaining})
            return self.deliver(uid, self.t(uid, "captcha_bad", remaining=remaining))
        if state == "order_target":
            if not valid_target(value, data["platform"]):
                return self.deliver(uid, self.t(uid, "invalid_target"))
            self.db.set_state(uid, "order_reason", **data, target=value)
            return self.deliver(uid, self.t(uid, "describe"))
        if state == "order_reason":
            if not 10 <= len(value) <= MAX_TEXT:
                return self.deliver(uid, self.t(uid, "invalid_reason"))
            subject = f"[{data['platform']}/{data['target_kind']}] {data['target']}\nReason: {value}"
            if len(subject) > MAX_TEXT:
                return self.deliver(uid, self.t(uid, "invalid_reason"))
            self.db.set_state(uid, "order_evidence", sid=data["sid"], nonce=data["nonce"], subject=subject)
            return self.deliver(uid, self.t(uid, "evidence"))
        if state == "order_subject":
            if len(value) < 10 or len(value) > MAX_TEXT:
                return self.deliver(uid, "Nhập mô tả hợp lệ dài 10–1.200 ký tự.")
            self.db.set_state(uid, "order_evidence", sid=data["sid"], nonce=data["nonce"], subject=value)
            return self.deliver(uid, "Gửi bằng chứng: liên kết, mô tả chi tiết hoặc một ảnh/tệp. "
                                "Bằng chứng phải liên quan đến vi phạm thực tế.\n/cancel để hủy.")
        if state == "order_evidence":
            kind, proof = self.proof(message)
            if not proof:
                return self.deliver(uid, "Cần gửi bằng chứng dạng văn bản, ảnh, video hoặc tệp.")
            o = self.db.create_order(uid, int(data["sid"]), data["subject"], kind, proof, data["nonce"])
            self.db.set_state(uid, "")
            if not o:
                return self.deliver(uid, "Không tạo được yêu cầu. Có thể đã đạt giới hạn đơn đang chờ.", BACK)
            self.admins_notify(
                f"<b>Yêu cầu mới #{o['id']}</b>\nKhách: <code>{uid}</code>\n"
                f"Dịch vụ ID: {o['service_id']}\nMô tả: {esc(o['subject'])}\n"
                f"Bằng chứng: {esc(proof[:200]) if kind == 'text' else kind}\n"
                f"Trạng thái: {esc(o['status'])}",
                (kind, proof) if kind != "text" else None,
            )
            self.deliver(uid, self.t(uid, "submitted", order_id=o["id"]))
            return self.order_detail(uid, o["id"])
        if state == "deposit_amount":
            number = re.sub(r"[.,\s]", "", value)
            if not number.isdigit() or not (10000 <= int(number) <= 100000000):
                return self.deliver(uid, "Số tiền không hợp lệ (10.000–100.000.000 VND).")
            dep = self.db.create_deposit(uid, int(number))
            if not dep:
                return self.deliver(uid, "Bạn đã có quá nhiều yêu cầu nạp đang chờ. Dùng /cancel để trở về menu.")
            self.db.set_state(uid, "deposit_proof", deposit_id=dep["id"])
            self.deliver(uid, f"<b>Thông tin chuyển khoản</b>\nNgân hàng: {esc(self.bank_name)}\n"
                             f"Chủ tài khoản: {esc(self.bank_owner)}\nSTK: <code>{esc(self.bank_account)}</code>\n"
                             f"Số tiền: <b>{money(dep['amount'])}</b>\n"
                             f"Nội dung CK: <code>TN{dep['id']}</code>\n\n"
                             "Sau khi chuyển khoản, gửi <b>ảnh chứng từ hoặc mã giao dịch</b> tại đây. "
                             "Hệ thống không tự ghi có nếu chưa được đối chiếu tại ngân hàng.")
            return
        if state == "deposit_proof":
            kind, proof = self.proof(message)
            if not proof:
                return self.deliver(uid, "Hãy gửi chứng từ hoặc mã giao dịch.")
            dep = self.db.submit_proof(int(data["deposit_id"]), uid, kind, proof)
            self.db.set_state(uid, "")
            if not dep:
                return self.deliver(uid, "Yêu cầu nạp này không còn hợp lệ. Liên hệ hỗ trợ.", BACK)
            self.deliver(uid, f"Đã nhận chứng từ nạp <b>#{dep['id']}</b>. "
                              "Ví chỉ được cộng sau khi Admin xác minh chuyển khoản thực tế.", BACK)
            return self.admins_notify(
                f"<b>Nạp ví cần xác minh #{dep['id']}</b>\nUser: <code>{uid}</code>\n"
                f"Số tiền khai báo: <b>{money(dep['amount'])}</b>\n"
                f"Chứng từ: {esc(proof[:180]) if kind == 'text' else kind}\n"
                f"Đối chiếu ngân hàng TRƯỚC khi dùng /approvedep {dep['id']}",
                (kind, proof) if kind != "text" else None,
            )
        if state == "support":
            if len(value) < 5 or len(value) > MAX_TEXT:
                return self.deliver(uid, "Nhập nội dung hỗ trợ dài 5–1.200 ký tự.")
            ticket = self.db.create_ticket(uid, value)
            self.db.set_state(uid, "")
            if not ticket:
                return self.deliver(uid, "Bạn đã gửi quá nhiều yêu cầu hỗ trợ trong 24 giờ. Vui lòng thử lại sau.")
            self.admins_notify(f"<b>Ticket #{ticket['id']}</b>\nUser: <code>{uid}</code>\n"
                               f"Nội dung: {esc(value)}\nTrả lời: /reply {ticket['id']} nội_dung")
            return self.deliver(uid, f"Đã tạo ticket <b>#{ticket['id']}</b>. Nhân viên sẽ phản hồi qua bot.", BACK)
        # Telegram Member ordering flow states
        if state == "tg_member_link":
            if not value or not re.match(r"^(https?://)?(t\.me|telegram\.me)/", value) and not re.match(r"^@[A-Za-z0-9_]{3,}", value):
                return self.deliver(uid, self.t(uid, "tg_member_invalid_link"))
            svc = self.provider.get_service(data["service_id"])
            if not svc:
                return self.deliver(uid, "Service not found.", self.back(uid))
            self.db.set_state(uid, "tg_member_qty", **data, link=value)
            return self.deliver(uid, self.t(uid, "tg_member_enter_qty", min_qty=svc.min_quantity, max_qty=svc.max_quantity))
        if state == "tg_member_qty":
            svc = self.provider.get_service(data["service_id"])
            if not svc:
                return self.deliver(uid, "Service not found.", self.back(uid))
            
            # Professional quantity validation
            min_qty = svc.min_quantity
            max_qty = svc.max_quantity
            
            # Check if value is a valid positive integer
            if not value.strip().isdigit():
                return self.deliver(uid, self.t(uid, "tg_member_qty_invalid_format", min_qty=min_qty, max_qty=max_qty))
            
            qty = int(value.strip())
            
            # Check for zero
            if qty == 0:
                return self.deliver(uid, self.t(uid, "tg_member_qty_zero", service_name=svc.name, min_qty=min_qty, max_qty=max_qty))
            
            # Check below minimum
            if qty < min_qty:
                return self.deliver(uid, self.t(uid, "tg_member_qty_below_min", 
                    service_name=svc.name, quantity=qty, min_qty=min_qty, max_qty=max_qty))
            
            # Check above maximum
            if qty > max_qty:
                return self.deliver(uid, self.t(uid, "tg_member_qty_above_max", 
                    service_name=svc.name, quantity=qty, min_qty=min_qty, max_qty=max_qty))
            
            # Quantity is valid - calculate total price
            api_price_per_1000 = svc.price_per_1000
            markup_percent = self.db.get_markup_percent()
            selling_price_per_1000 = (api_price_per_1000 * Decimal(100 + markup_percent) / Decimal(100)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            # total = quantity * selling_price_per_1000 / 1000
            total = (Decimal(qty) * selling_price_per_1000 / Decimal(1000)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            total_int = int(total)  # VND integer
            user = self.db.get_user(uid)
            balance = user["balance"] if user else 0
            if total_int > balance:
                return self.deliver(uid, self.t(uid, "tg_member_insufficient_balance", need=total_int, have=balance),
                                    keyboard(((self.t(uid, "cancel"), "tools:engagement"),)))
            
            # Store confirmation data
            self.db.set_state(uid, "tg_member_confirm", **data, quantity=qty,
                              unit_price_milli=int(selling_price_per_1000 * 1000),  # milli VND
                              api_price_milli=int(svc.price_per_1000 * 1000),
                              markup_percent=markup_percent,
                              total=total_int,
                              nonce=secrets.token_hex(8))
            
            # Show professional confirmation with [Xác nhận đặt hàng] [Hủy] buttons
            self.deliver(uid, self.t(uid, "tg_member_qty_valid",
                service_name=svc.name,
                link=esc(data["link"]),
                quantity=qty,
                total=total_int),
                keyboard(((self.t(uid, "confirm_pay"), "tg_member_confirm_pay"), (self.t(uid, "cancel"), "tools:engagement"))))
            return
        if state == "tg_member_confirm":
            # Already confirmed via callback, should not reach here
            pass
        self.db.set_state(uid, "")
        self.send_home(uid)

    def handle_admin(self, uid, msg, cmd, arg):
        if not self.is_admin(uid):
            self.deliver(uid, "Lệnh này chỉ dành cho Admin.")
            return
        parts = arg.split(maxsplit=2)
        if cmd == "admin":
            s = self.db.stats()
            return self.deliver(uid, f"<b>Admin</b>\nUsers: {s['users']}\nOrders: {s['orders']}\n"
                                f"Nạp chờ duyệt: {s['pending_deposits']}\n\n"
                                "/ordersadmin, /deposits, /setprice ID VND, /quote ID VND, "
                                "/approve ID, /done ID, /reject ID, /approvedep ID, /rejectdep ID, "
                                "/reply ID nội_dung, /credit USER_ID VND, /setbanner (trả lời ảnh/GIF)")
        if cmd == "ordersadmin":
            records = self.db.list_orders(limit=15)
            return self.deliver(uid, "<b>15 đơn gần đây</b>\n" + "\n".join(
                f"#{r['id']} · <code>{r['user_id']}</code> · {esc(r['status'])} · {money(r['amount'])}"
                for r in records) if records else "Chưa có đơn.")
        if cmd == "deposits":
            records = self.db.list_deposits()
            return self.deliver(uid, "<b>Yêu cầu nạp chờ xác minh</b>\n" + "\n".join(
                f"#{r['id']} · <code>{r['user_id']}</code> · {money(r['amount'])}"
                for r in records) if records else "Không có yêu cầu chờ.")
        if cmd == "setbanner":
            reply = msg.get("reply_to_message") or {}
            if reply.get("animation"):
                kind, file_id = "animation", reply["animation"]["file_id"]
            elif reply.get("photo"):
                kind, file_id = "photo", reply["photo"][-1]["file_id"]
            else:
                return self.deliver(uid, "Hãy reply vào ảnh hoặc GIF bằng lệnh /setbanner.")
            self.db.set_setting("banner_kind", kind)
            self.db.set_setting("banner_id", file_id)
            return self.deliver(uid, "Đã cập nhật banner cho menu /start.")
        if cmd in ("setprice", "quote", "credit"):
            if len(parts) != 2 or not all(x.isdigit() for x in parts):
                return self.deliver(uid, f"Cú pháp: /{cmd} ID SỐ_TIỀN_VND")
            target, amount = map(int, parts)
            if cmd == "setprice":
                ok = self.db.set_price(target, amount)
                return self.deliver(uid, "Đã thay đổi giá cho các đơn mới." if ok else "Không tìm thấy dịch vụ.")
            if cmd == "credit":
                ok = self.db.credit(target, amount)
                if ok:
                    self.deliver(target, f"Admin đã ghi có <b>{money(amount)}</b> vào ví của bạn.")
                return self.deliver(uid, "Đã ghi có và lưu sổ cái." if ok else "User chưa tồn tại/số tiền không hợp lệ.")
            order = self.db.quote_order(target, amount)
            if not order:
                return self.deliver(uid, "Chỉ báo giá cho đơn đang chờ báo giá; số tiền phải > 0.")
            self.deliver(order["user_id"], f"Yêu cầu <b>#{target}</b> đã được báo giá: "
                         f"<b>{money(amount)}</b>. Mở đơn để thanh toán.",
                         keyboard((("Xem đơn / thanh toán", f"order:{target}"),)))
            return self.deliver(uid, f"Đã gửi báo giá #{target}.")
        if cmd in ("approve", "done", "reject"):
            if len(parts) != 1 or not parts[0].isdigit():
                return self.deliver(uid, f"Cú pháp: /{cmd} ORDER_ID")
            oid = int(parts[0])
            order = (self.db.reject_order(oid) if cmd == "reject" else
                     self.db.set_order_status(oid, "processing" if cmd == "approve" else "completed"))
            if not order:
                return self.deliver(uid, "Không thể chuyển trạng thái (đơn không tồn tại hoặc sai trạng thái).")
            detail = "Tiền đã hoàn về ví." if cmd == "reject" and order["paid"] else ""
            self.deliver(order["user_id"], f"Đơn <b>#{oid}</b>: "
                         f"<b>{esc(STATUSES[order['status']])}</b>. {detail}")
            return self.deliver(uid, f"Đã cập nhật #{oid}: {esc(order['status'])}.")
        if cmd in ("approvedep", "rejectdep"):
            if len(parts) != 1 or not parts[0].isdigit():
                return self.deliver(uid, f"Cú pháp: /{cmd} DEPOSIT_ID")
            dep = self.db.deposit_action(int(parts[0]), cmd == "approvedep")
            if not dep:
                return self.deliver(uid, "Đơn nạp không tồn tại, không ở trạng thái chờ hoặc đã xử lý.")
            self.deliver(dep["user_id"], f"Nạp ví <b>#{dep['id']}</b>: "
                         f"{'đã xác nhận và cộng ' + money(dep['amount']) if cmd == 'approvedep' else 'không được chấp nhận' }.")
            return self.deliver(uid, f"Đã xử lý nạp ví #{dep['id']} ({esc(dep['status'])}).")
        if cmd == "reply":
            if len(parts) < 2 or not parts[0].isdigit() or not arg.partition(" ")[2].strip():
                return self.deliver(uid, "Cú pháp: /reply TICKET_ID nội dung trả lời")
            ticket = self.db.ticket(int(parts[0]))
            if not ticket:
                return self.deliver(uid, "Ticket không tồn tại.")
            body = arg.partition(" ")[2].strip()[:MAX_TEXT]
            delivered = self.deliver(ticket["user_id"],
                                     f"<b>Phản hồi ticket #{ticket['id']}</b>\n{esc(body)}", BACK)
            return self.deliver(uid, "Đã gửi phản hồi." if delivered else "Không gửi được phản hồi.")
        self.deliver(uid, "Lệnh Admin không được hỗ trợ.")

    def handle_message(self, msg):
        person = msg.get("from") or {}
        uid = person.get("id")
        if not uid or msg.get("chat", {}).get("type") != "private":
            return
        text = (msg.get("text") or "").strip()
        match = re.match(r"^/(\w+)(?:@\w+)?(?:\s+([\s\S]*))?$", text)
        cmd, arg = (match.group(1).lower(), (match.group(2) or "").strip()) if match else ("", "")
        referral = None
        if cmd == "start" and re.fullmatch(r"ref_\d{1,16}", arg):
            referral = int(arg[4:])
        self.db.ensure_user(uid, person.get("username") or "", person.get("first_name") or "", referral)
        if cmd in ("start", "menu", "cancel"):
            user = self.db.get_user(uid)
            if not user["verified_at"]:
                return self.start_verification(uid, force=cmd == "cancel")
            if not user["language"]:
                return self.choose_language(uid)
            self.db.set_state(uid, "")
            return self.send_home(uid, welcome=cmd == "start")
        if cmd in ("admin", "ordersadmin", "deposits", "setprice", "quote", "credit",
                   "approve", "done", "reject", "approvedep", "rejectdep", "reply", "setbanner"):
            return self.handle_admin(uid, msg, cmd, arg)
        user = self.db.get_user(uid)
        if not user["verified_at"]:
            state, data = self.db.get_state(uid)
            if state != "captcha":
                return self.start_verification(uid)
            return self.process_state(uid, msg, state, data)
        if not user["language"]:
            return self.choose_language(uid)
        if cmd in ("language", "lang"):
            self.db.set_state(uid, "")
            return self.choose_language(uid)
        if cmd == "canceldeposit":
            if not arg.isdigit():
                return self.deliver(uid, "Cú pháp: /canceldeposit DEPOSIT_ID")
            ok = self.db.cancel_deposit(int(arg), uid)
            self.db.set_state(uid, "")
            return self.deliver(uid, "Đã hủy đơn nạp chưa gửi chứng từ." if ok else
                                "Không thể hủy: đơn không thuộc về bạn hoặc đã chuyển sang xét duyệt.", BACK)
        if cmd == "proof":
            parts = arg.split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                return self.deliver(uid, "Cú pháp: /proof DEPOSIT_ID mã_giao_dịch")
            dep = self.db.submit_proof(int(parts[0]), uid, "text", parts[1][:MAX_TEXT])
            if not dep:
                return self.deliver(uid, "Không tìm thấy khoản nạp đang chờ chứng từ.")
            self.db.set_state(uid, "")
            self.admins_notify(f"Nạp ví #{dep['id']} cần xác minh · User {uid} · "
                               f"{money(dep['amount'])} · Chứng từ {esc(parts[1][:200])}")
            return self.deliver(uid, "Đã gửi chứng từ; chờ Admin kiểm tra ngân hàng.")
        state, data = self.db.get_state(uid)
        if state:
            return self.process_state(uid, msg, state, data)
        if cmd == "wallet":
            return self.wallet(uid)
        if cmd == "mydeposits":
            return self.my_deposits(uid)
        if cmd == "services":
            return self.services(uid)
        if cmd == "orders":
            return self.orders(uid)
        if cmd == "help":
            return self.faq(uid)
        self.deliver(uid, "Select an option or use /menu.", self.home_keyboard(uid))

    def handle_callback(self, query):
        person = query.get("from") or {}
        uid = person.get("id")
        if not uid:
            return
        try:
            self.api.call("answerCallbackQuery", callback_query_id=query["id"])
        except ApiError as exc:
            LOG.info("Không ACK callback: %s", exc)
        # Require a private chat, not a forwarded/shared inline message.
        if (query.get("message") or {}).get("chat", {}).get("type") != "private":
            return
        self.db.ensure_user(uid, person.get("username") or "", person.get("first_name") or "")
        action = query.get("data", "")
        user = self.db.get_user(uid)
        if not user["verified_at"]:
            return self.start_verification(uid)
        if re.fullmatch(r"lang:(vi|en)", action):
            self.db.set_language(uid, action.split(":", 1)[1])
            self.db.set_state(uid, "")
            return self.send_home(uid, welcome=True)
        if not user["language"]:
            return self.choose_language(uid)
        if action == "language":
            self.db.set_state(uid, "")
            return self.choose_language(uid)
        if action == "home":
            self.db.set_state(uid, "")
            return self.send_home(uid)
        if action == "wallet":
            return self.wallet(uid)
        if action == "mydeposits":
            return self.my_deposits(uid)
        if action == "services":
            self.db.set_state(uid, "")
            return self.services(uid)
        if re.fullmatch(r"platform:(telegram|tiktok|youtube|facebook|instagram)", action):
            return self.services(uid, platform=action.split(":", 1)[1])
        if action == "tools":
            self.db.set_state(uid, "")
            return self.tools_menu(uid)
        if action == "tools:report":
            self.db.set_state(uid, "")
            return self.services(uid)
        if action == "tools:engagement":
            self.db.set_state(uid, "")
            return self.engagement_menu(uid)
        # New engagement platform/category callbacks
        if action.startswith("engagement:platform:"):
            self.db.set_state(uid, "")
            platform_slug = action.split(":", 2)[2]
            return self.engagement_platform(uid, platform_slug)
        if action.startswith("engagement:category:"):
            self.db.set_state(uid, "")
            try:
                category_id = int(action.split(":", 2)[2])
            except ValueError:
                return self.deliver(uid, "Invalid category.", self.back(uid))
            category = self.db.get_engagement_category(category_id)
            if not category:
                return self.deliver(uid, "Category not found.", self.back(uid))
            # Route to appropriate handler based on category slug
            if category["slug"] == "members":
                return self.telegram_members(uid)
            elif category["slug"] == "views":
                return self.telegram_views(uid)
            else:
                return self.deliver(uid, "Service not available.", 
                                    keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))
        if action.startswith("engagement:coming_soon:"):
            self.db.set_state(uid, "")
            return self.deliver(uid, self.t(uid, "engagement_coming_soon"),
                                keyboard(((self.t(uid, "back_engagement"), "tools:engagement"),)))
        # Backward compatibility: old callback for telegram members
        if action == "engagement:telegram_members":
            self.db.set_state(uid, "")
            return self.telegram_members(uid)
        if action == "tools:buy":
            self.db.set_state(uid, "")
            return self.services(uid, tool_only=True)
        if action == "tools:sub":
            self.db.set_state(uid, "")
            return self.tool_subscription(uid)
        if action == "orders":
            return self.orders(uid)
        if action == "deposit":
            return self.begin_deposit(uid)
        if action == "support":
            self.db.set_state(uid, "support")
            return self.deliver(uid, "Nhập nội dung cần hỗ trợ (5–1.200 ký tự). /cancel để hủy.")
        if action == "referral":
            return self.referral(uid)
        if action == "faq":
            return self.faq(uid)
        if action == "changelog":
            return self.deliver(uid, "<b>Changelog v2.0</b>\n• Xác minh phép tính và chọn 2 ngôn ngữ (Việt / English)\n"
                                "• Báo cáo theo nền tảng/loại đối tượng\n• GIF caption + nút menu\n"
                                "• Quản lý ví, đơn hàng, hỗ trợ và giới thiệu", BACK)
        if re.fullmatch(r"service:\d+", action):
            return self.service_detail(uid, int(action.split(":")[1]))
        if re.fullmatch(r"new:\d+", action):
            return self.begin_order(uid, int(action.split(":")[1]))
        if re.fullmatch(r"target:\d+:(profile|channel|group|post)", action):
            _, sid, kind = action.split(":")
            return self.begin_order(uid, int(sid), kind)
        if re.fullmatch(r"order:\d+", action):
            return self.order_detail(uid, int(action.split(":")[1]))
        if re.fullmatch(r"tg_member_select:\d+", action):
            service_id = action.split(":")[1]
            return self.tg_member_start_order(uid, service_id)
        if action == "tg_member_confirm_pay":
            return self.tg_member_confirm_pay(uid)
        if re.fullmatch(r"pay:\d+", action):
            oid = int(action.split(":")[1])
            outcome = self.db.pay_order(oid, uid)
            if outcome == "paid":
                self.admins_notify(f"<b>Đơn #{oid} đã thanh toán từ ví</b>.\nKiểm tra hồ sơ và /approve {oid} hoặc /reject {oid}.")
                return self.deliver(uid, f"Đã thanh toán đơn <b>#{oid}</b>. Chờ Admin xét duyệt.", BACK)
            messages = {"insufficient": "Số dư ví không đủ. Hãy nạp tiền và thanh toán lại.",
                        "already_paid": "Đơn này đã thanh toán.",
                        "not_payable": "Đơn hiện không thể thanh toán.",
                        "missing": "Bạn không có quyền truy cập đơn này."}
            return self.deliver(uid, messages.get(outcome, "Lỗi thanh toán."), BACK)
        self.deliver(uid, "Thao tác không hợp lệ, quay lại /menu.")

    def serve(self):
        me = self.api.call("getMe")
        self.username = me["username"]
        self.api.call("deleteWebhook", drop_pending_updates=False)
        self.api.call("setMyCommands", commands=[
            {"command": "start", "description": "Xác minh / mở menu chính"},
            {"command": "wallet", "description": "Kiểm tra ví"},
            {"command": "services", "description": "Danh mục dịch vụ"},
            {"command": "orders", "description": "Đơn của tôi"},
            {"command": "help", "description": "Hướng dẫn"},
            {"command": "cancel", "description": "Hủy thao tác"},
            {"command": "language", "description": "Thay đổi ngôn ngữ"},
        ])
        LOG.info("Bot @%s đã hoạt động, admin count=%s", self.username, len(self.admins))
        retry = 1
        while self.running:
            try:
                updates = self.api.call("getUpdates", offset=self.offset, timeout=25,
                                        limit=50, allowed_updates=["message", "callback_query"])
                retry = 1
                for update in updates:
                    # Move offset even on handler failure so one poisoned update doesn't block all traffic.
                    self.offset = max(self.offset, update["update_id"] + 1)
                    try:
                        if "message" in update:
                            self.handle_message(update["message"])
                        elif "callback_query" in update:
                            self.handle_callback(update["callback_query"])
                    except Exception:
                        LOG.exception("Lỗi xử lý update_id=%s", update["update_id"])
                    finally:
                        try:
                            self.db.set_setting("poll_offset", str(self.offset))
                        except Exception:
                            LOG.exception("Không lưu được poll_offset; tiếp tục với offset trong bộ nhớ")
            except (ApiError, OSError):
                LOG.exception("Lỗi polling; sẽ thử lại")
                time.sleep(min(retry, 30))
                retry *= 2
        LOG.info("Polling đã dừng")

    def stop(self, *_):
        if self.running:
            LOG.info("Nhận tín hiệu dừng; đang kết thúc an toàn")
        self.running = False


def main():
    env_file()
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = App()
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    try:
        app.serve()
    finally:
        app.db.close()


if __name__ == "__main__":
    main()
