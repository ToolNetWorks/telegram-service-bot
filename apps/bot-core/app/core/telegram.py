"""Telegram Bot API transport layer - stdlib only, long polling compatible."""
from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core.config import BotConfig

LOG = logging.getLogger("botcore.telegram")


class TelegramAPIError(Exception):
    """Telegram API error - never contains sensitive data."""
    pass


class TelegramClient:
    """Minimal Telegram Bot API client using stdlib only."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.bot_token}/"
        self._username: str = ""
        self._gif_cache: dict[str, tuple[str, str]] = {}  # name -> (file_id, signature)
    
    @property
    def username(self) -> str:
        return self._username
    
    @username.setter
    def username(self, value: str) -> None:
        self._username = value
    
    def call(self, method: str, **params) -> Any:
        """Make a Telegram API call (JSON)."""
        url = self.base_url + method
        data = json.dumps(params, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("description", f"HTTP {exc.code}")
            except (ValueError, OSError):
                detail = f"HTTP {exc.code}"
            raise TelegramAPIError(f"Telegram {method}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or type(exc).__name__
            raise TelegramAPIError(f"Network/API error at {method}: {str(reason)[:200]}") from None
        
        if not body.get("ok"):
            raise TelegramAPIError(f"Telegram {method}: {body.get('description', 'unknown error')}")
        return body.get("result")
    
    def call_multipart(self, method: str, params: dict, files: list[tuple[str, str, str, bytes]]) -> Any:
        """Make a multipart/form-data Telegram API call (for file uploads)."""
        boundary = "----BotCore" + secrets.token_hex(16)
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
            self.base_url + method,
            data=bytes(payload),
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
            raise TelegramAPIError(f"Telegram {method}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or type(exc).__name__
            raise TelegramAPIError(f"Network/API error at {method}: {str(reason)[:200]}") from None
        
        if not result.get("ok"):
            raise TelegramAPIError(f"Telegram {method}: {result.get('description', 'unknown error')}")
        return result.get("result")
    
    def send_message(self, chat_id: int, text: str, markup: dict | None = None) -> dict:
        """Send a text message."""
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if markup:
            data["reply_markup"] = markup
        return self.call("sendMessage", **data)
    
    def send_media(self, chat_id: int, kind: str, file_id: str, caption: str, markup: dict | None = None) -> dict:
        """Send media using a cached file_id."""
        method = {"photo": "sendPhoto", "animation": "sendAnimation", "video": "sendVideo"}.get(kind)
        if not method:
            raise TelegramAPIError(f"Unsupported media kind: {kind}")
        data = {"chat_id": chat_id, kind: file_id, "caption": caption, "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = markup
        return self.call(method, **data)
    
    def send_animation_file(self, chat_id: int, path: Path, caption: str, markup: dict | None = None) -> dict:
        """Upload and send an animation file."""
        content = path.read_bytes()
        if content[:6].startswith(b"GIF8"):
            filename, content_type = path.name, "image/gif"
        else:
            filename, content_type = path.name, "video/mp4"
        
        data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = markup
        
        return self.call_multipart("sendAnimation", data, [("animation", filename, content_type, content)])
    
    def answer_callback_query(self, callback_query_id: str) -> None:
        """Acknowledge a callback query."""
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_query_id)
        except TelegramAPIError as exc:
            LOG.info("Failed to ACK callback: %s", exc)
    
    def delete_webhook(self, drop_pending_updates: bool = False) -> None:
        """Delete webhook to ensure long polling works."""
        self.call("deleteWebhook", drop_pending_updates=drop_pending_updates)
    
    def set_my_commands(self, commands: list[dict]) -> None:
        """Set bot commands."""
        self.call("setMyCommands", commands=commands)
    
    def get_me(self) -> dict:
        """Get bot info."""
        return self.call("getMe")
    
    def get_updates(self, offset: int, timeout: int = 25, limit: int = 50) -> list[dict]:
        """Get updates via long polling."""
        return self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            limit=limit,
            allowed_updates=["message", "callback_query"],
        )