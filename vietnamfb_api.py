#!/usr/bin/env python3
"""VietnamFB SMM Panel API Client.

Tham khảo spec phổ biến: PerfectPanel / SMM Raja / SmartPanel.
Endpoint: https://vietnamfb.com?mc=panel&site=<action>&api_key=<key>
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

LOG = logging.getLogger("vietnamfb")


@dataclass
class Service:
    """Dịch vụ từ API."""
    service_id: str
    name: str
    category_id: str
    category_name: str
    platform_id: str
    platform_name: str
    price_per_1000: Decimal  # giá cho 1000 đơn vị (VND)
    min_quantity: int
    max_quantity: int
    average_time: str
    type: str
    service_note: str
    refill: bool
    cancel: bool


@dataclass
class OrderResult:
    """Kết quả tạo đơn từ API."""
    order_id: str
    charge: Optional[Decimal] = None
    start_count: Optional[int] = None
    remains: Optional[int] = None
    status: str = "Pending"
    currency: str = "VND"


@dataclass
class BalanceInfo:
    """Thông tin số dư API."""
    balance: Decimal
    currency: str = "VND"


class VietnamFBError(Exception):
    """Lỗi từ API VietnamFB.

    ``definitive`` is True only when the provider certainly did not accept the
    order (so a wallet refund is safe).  Network/timeout/invalid-response
    errors are ambiguous and must be reconciled instead of refunded blindly.
    """
    def __init__(self, message: str, code: Optional[int] = None, definitive: bool = True):
        super().__init__(message)
        self.code = code
        self.definitive = definitive


class VietnamFBAPI:
    """Client cho VietnamFB SMM Panel."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://vietnamfb.com",
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._services_cache: Optional[list[Service]] = None
        self._cache_time = 0
        self._cache_ttl = 300  # 5 phút

    def _post(self, site: str, data: dict[str, Any]) -> dict[str, Any]:
        """Gửi POST request đến API."""
        url = f"{self.base_url}?mc=panel&site={site}&api_key={self.api_key}"
        payload = urllib.parse.urlencode(data).encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json, text/html",
        }
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                LOG.debug("API %s response: %s", site, raw[:500])
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            LOG.error("API %s HTTP %s: %s", site, e.code, body[:200])
            raise VietnamFBError(f"HTTP {e.code}: {body}", e.code,
                                 definitive=e.code != 408 and e.code < 500) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", "network error")
            LOG.error("API %s network error: %s", site, reason)
            raise VietnamFBError(f"Network error: {reason}", definitive=False) from None
        except json.JSONDecodeError as e:
            LOG.error("API %s invalid JSON: %s", site, e)
            raise VietnamFBError(f"Invalid JSON response: {e}", definitive=False) from None

    def get_services(self, force_refresh: bool = False) -> list[Service]:
        """Lấy danh sách tất cả dịch vụ, cache 5 phút."""
        now = time.time()
        if not force_refresh and self._services_cache and (now - self._cache_time) < self._cache_ttl:
            return self._services_cache

        resp = self._post("getServiceByCategory", {})  # không truyền category_id -> trả tất cả
        if not isinstance(resp, list):
            raise VietnamFBError(f"Unexpected response format: {type(resp)}")

        services = []
        for item in resp:
            try:
                # API trả giá cho 1000 đơn vị (rate)
                price_raw = str(item.get("price", "0"))
                price_per_1000 = Decimal(price_raw).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

                svc = Service(
                    service_id=str(item["id"]),
                    name=str(item.get("name", "")),
                    category_id=str(item.get("category_id", "")),
                    category_name=str(item.get("category_name", "")),
                    platform_id=str(item.get("platform_id", "")),
                    platform_name=str(item.get("platform_name", "")),
                    price_per_1000=price_per_1000,
                    min_quantity=int(item.get("min_quantity", 0)),
                    max_quantity=int(item.get("max_quantity", 0)),
                    average_time=str(item.get("average_time", "")),
                    type=str(item.get("type", "Default")),
                    service_note=str(item.get("service_note", "")),
                    refill=bool(item.get("refill", False)) if "refill" in item else False,
                    cancel=bool(item.get("cancel", False)) if "cancel" in item else False,
                )
                services.append(svc)
            except (KeyError, ValueError, TypeError) as e:
                LOG.warning("Skip invalid service item: %s, error: %s", item, e)
                continue

        self._services_cache = services
        self._cache_time = now
        LOG.info("Fetched %d services from VietnamFB", len(services))
        return services

    def get_telegram_member_services(self) -> list[Service]:
        """Lọc dịch vụ Telegram Group Members (category_id=18)."""
        all_services = self.get_services()
        return [s for s in all_services if s.category_id == "18"]

    def get_service(self, service_id: str) -> Optional[Service]:
        """Lấy chi tiết một dịch vụ theo ID."""
        for svc in self.get_services():
            if svc.service_id == service_id:
                return svc
        return None

    def add_order(
        self,
        service_id: str,
        link: str,
        quantity: int,
        runs: Optional[int] = None,
        interval: Optional[int] = None,
    ) -> OrderResult:
        """Tạo đơn hàng mới."""
        data = {
            "service": service_id,
            "link": link,
            "quantity": str(quantity),
        }
        if runs is not None:
            data["runs"] = str(runs)
        if interval is not None:
            data["interval"] = str(interval)

        resp = self._post("add", data)
        if not isinstance(resp, dict):
            raise VietnamFBError(f"Unexpected add order response: {resp}", definitive=False)

        # Kiểm tra lỗi
        if "error" in resp:
            raise VietnamFBError(str(resp["error"]))
        if resp.get("status") == "error":
            raise VietnamFBError(str(resp.get("message", "Unknown error")))

        order_id = str(resp.get("order", resp.get("order_id", "")))
        if not order_id:
            raise VietnamFBError("Missing order ID in response", definitive=False)

        return OrderResult(
            order_id=order_id,
            charge=Decimal(str(resp.get("charge", 0))) if resp.get("charge") else None,
            start_count=int(resp["start_count"]) if resp.get("start_count") else None,
            remains=int(resp["remains"]) if resp.get("remains") else None,
            status=str(resp.get("status", "Pending")),
            currency=str(resp.get("currency", "VND")),
        )

    def get_order_status(self, order_id: str) -> OrderResult:
        """Tra cứu trạng thái đơn hàng."""
        resp = self._post("status", {"order": order_id})
        if not isinstance(resp, dict):
            # Một số API trả về list cho status
            if isinstance(resp, list) and resp:
                resp = resp[0]
            else:
                raise VietnamFBError(f"Unexpected status response: {resp}")

        if "error" in resp:
            raise VietnamFBError(str(resp["error"]))

        return OrderResult(
            order_id=order_id,
            charge=Decimal(str(resp.get("charge", 0))) if resp.get("charge") else None,
            start_count=int(resp["start_count"]) if resp.get("start_count") else None,
            remains=int(resp["remains"]) if resp.get("remains") else None,
            status=str(resp.get("status", "Pending")),
            currency=str(resp.get("currency", "VND")),
        )

    def get_multiple_status(self, order_ids: list[str]) -> list[OrderResult]:
        """Tra cứu nhiều đơn hàng cùng lúc."""
        if not order_ids:
            return []
        resp = self._post("status", {"orders": ",".join(order_ids)})
        results = []
        if isinstance(resp, list):
            for item in resp:
                try:
                    results.append(OrderResult(
                        order_id=str(item.get("order", "")),
                        charge=Decimal(str(item.get("charge", 0))) if item.get("charge") else None,
                        start_count=int(item["start_count"]) if item.get("start_count") else None,
                        remains=int(item["remains"]) if item.get("remains") else None,
                        status=str(item.get("status", "Pending")),
                        currency=str(item.get("currency", "VND")),
                    ))
                except (KeyError, ValueError, TypeError) as e:
                    LOG.warning("Skip invalid status item: %s, error: %s", item, e)
        return results

    def get_balance(self) -> BalanceInfo:
        """Kiểm tra số dư API."""
        resp = self._post("balance", {})
        if not isinstance(resp, dict):
            raise VietnamFBError(f"Unexpected balance response: {resp}")
        if "error" in resp:
            raise VietnamFBError(str(resp["error"]))
        balance = Decimal(str(resp.get("balance", 0)))
        currency = str(resp.get("currency", "VND"))
        return BalanceInfo(balance=balance, currency=currency)

    def refill_order(self, order_id: str) -> dict:
        """Yêu cầu refill đơn hàng."""
        return self._post("refill", {"order": order_id})

    def cancel_order(self, order_id: str) -> dict:
        """Hủy đơn hàng."""
        return self._post("cancel", {"order": order_id})


def create_api_client() -> VietnamFBAPI:
    """Tạo client từ environment variables."""
    api_key = os.getenv("VIETNAMFB_API_KEY")
    base_url = os.getenv("VIETNAMFB_BASE_URL", "https://vietnamfb.com")
    if not api_key:
        raise RuntimeError("VIETNAMFB_API_KEY not set in environment")
    return VietnamFBAPI(api_key=api_key, base_url=base_url)