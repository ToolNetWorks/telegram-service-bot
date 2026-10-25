"""Engagement API contract, safety and provider tests."""
from __future__ import annotations

import asyncio
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.providers import provider_registry
from app.providers.base import (
    Provider,
    ProviderError,
    ProviderOrderData,
    ProviderServiceData,
)
from app.services.catalog import CatalogService
from app.services.orders import DuplicateInFlightError, OrderService

TOKEN = {"X-Internal-Token": "test_token"}


class FakeVietnamFB(Provider):
    name = "vietnamfb"

    def __init__(self) -> None:
        self.mode = "success"
        self.create_calls = 0
        self.status_calls = 0

    @property
    def configured(self) -> bool:
        return True

    async def get_services(self, force_refresh: bool = False) -> list[ProviderServiceData]:
        return [
            ProviderServiceData("1720", "Telegram Members HQ", Decimal("40.686"), 10, 1_000_000),
            ProviderServiceData("1510", "Telegram Members PLUS", Decimal("47.664"), 10, 1_000_000),
            ProviderServiceData("1694", "Telegram Premium Members", Decimal("142.330"), 1, 500_000),
        ]

    async def create_order(self, service_id: str, quantity: int, link: str) -> ProviderOrderData:
        self.create_calls += 1
        if self.mode == "definitive":
            raise ProviderError("Provider rejected service", definitive=True)
        if self.mode == "timeout":
            raise ProviderError("Provider timeout", definitive=False)
        return ProviderOrderData(
            order_id="provider-order-1",
            charge=Decimal("40.686"),
            status="processing",
            raw={"service": service_id, "quantity": quantity, "link": link},
        )

    async def get_order_status(self, provider_order_id: str) -> dict:
        self.status_calls += 1
        return {
            "provider_order_id": provider_order_id,
            "status": "completed",
            "charge": Decimal("40.686"),
        }

    async def get_balance(self) -> Decimal:
        return Decimal("1000.00")


class SlowVietnamFB(FakeVietnamFB):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_order(self, service_id: str, quantity: int, link: str) -> ProviderOrderData:
        self.create_calls += 1
        self.started.set()
        await self.release.wait()
        return ProviderOrderData("provider-order-slow", Decimal("40.686"), "processing")


class EngagementAPITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original_provider = provider_registry.get("vietnamfb")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.original_provider is not None:
            provider_registry.register(cls.original_provider)

    def setUp(self) -> None:
        self.provider = FakeVietnamFB()
        provider_registry.register(self.provider)
        reset_rate_limits()
        self.client = TestClient(app)

    # -- health -----------------------------------------------------

    def test_health_live(self) -> None:
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "alive")

    def test_health_ready(self) -> None:
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["catalog"], "loaded")

    def test_health_dependencies(self) -> None:
        response = self.client.get("/health/dependencies")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["providers"]["vietnamfb"], "ok")

    # -- auth -------------------------------------------------------

    def test_platforms_requires_token(self) -> None:
        self.assertEqual(self.client.get("/v1/platforms").status_code, 401)

    def test_platforms_rejects_wrong_token(self) -> None:
        response = self.client.get("/v1/platforms", headers={"X-Internal-Token": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_bearer_token_accepted(self) -> None:
        response = self.client.get("/v1/platforms", headers={"Authorization": "Bearer test_token"})
        self.assertEqual(response.status_code, 200)

    # -- catalog ----------------------------------------------------

    def test_platforms_include_coming_soon(self) -> None:
        response = self.client.get("/v1/platforms", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        platforms = {item["slug"]: item for item in response.json()["platforms"]}
        # VietnamFB platforms + Telegram + Coming Soon platforms
        expected_platforms = {
            "facebook", "instagram", "threads", "tiktok",
            "telegram", "youtube", "twitter", "shopee"
        }
        self.assertEqual(set(platforms), expected_platforms)
        self.assertTrue(platforms["telegram"]["enabled"])
        self.assertTrue(platforms["youtube"]["coming_soon"])
        self.assertTrue(platforms["twitter"]["coming_soon"])
        self.assertTrue(platforms["shopee"]["coming_soon"])
        # VietnamFB platforms should be enabled
        self.assertTrue(platforms["facebook"]["enabled"])
        self.assertTrue(platforms["instagram"]["enabled"])
        self.assertTrue(platforms["threads"]["enabled"])
        self.assertTrue(platforms["tiktok"]["enabled"])

    def test_telegram_categories_include_views(self) -> None:
        response = self.client.get("/v1/platforms/telegram/categories", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        categories = {item["slug"]: item for item in response.json()["categories"]}
        self.assertTrue(categories["members"]["enabled"])
        self.assertFalse(categories["views"]["enabled"])
        self.assertTrue(categories["views"]["coming_soon"])

    def test_unknown_platform_404(self) -> None:
        response = self.client.get("/v1/platforms/nope/categories", headers=TOKEN)
        self.assertEqual(response.status_code, 404)

    def test_member_services(self) -> None:
        response = self.client.get("/v1/categories/101/services", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        services = response.json()["services"]
        self.assertEqual([item["id"] for item in services], [1720, 1510, 1694])
        self.assertEqual(services[0]["rate_milli"], 40686)
        self.assertEqual(services[0]["cost_source"], "provider")

    def test_views_have_no_services(self) -> None:
        response = self.client.get("/v1/categories/102/services", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["services"], [])

    def test_get_category_and_service(self) -> None:
        category = self.client.get("/v1/categories/101", headers=TOKEN)
        self.assertEqual(category.status_code, 200)
        self.assertEqual(category.json()["slug"], "members")

        service = self.client.get("/v1/services/1720", headers=TOKEN)
        self.assertEqual(service.status_code, 200)
        self.assertEqual(service.json()["provider_service_id"], "1720")

    def test_provider_outage_uses_configured_cost_source(self) -> None:
        async def fail_services(force_refresh: bool = False):
            raise ProviderError("provider down", definitive=False)

        with patch.object(self.provider, "get_services", side_effect=fail_services):
            response = self.client.get("/v1/categories/101/services", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["services"][0]["cost_source"], "configured")

    # -- orders -----------------------------------------------------

    def order_payload(self, **overrides) -> dict:
        payload = {
            "service_id": 1720,
            "quantity": 1000,
            "link": "https://t.me/testgroup",
            "idempotency_key": "test-key-1",
        }
        payload.update(overrides)
        return payload

    def test_create_order_success(self) -> None:
        response = self.client.post("/v1/orders", headers=TOKEN, json=self.order_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["provider_order_id"], "provider-order-1")
        self.assertEqual(body["charge_milli"], 40686)
        self.assertEqual(self.provider.create_calls, 1)

    def test_definitive_provider_error(self) -> None:
        self.provider.mode = "definitive"
        response = self.client.post("/v1/orders", headers=TOKEN, json=self.order_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertTrue(body["definitive"])
        self.assertEqual(body["status"], "failed")

    def test_ambiguous_provider_error_requires_reconciliation(self) -> None:
        self.provider.mode = "timeout"
        response = self.client.post("/v1/orders", headers=TOKEN, json=self.order_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertFalse(body["definitive"])
        self.assertTrue(body["reconciliation_required"])
        self.assertEqual(body["status"], "pending_reconciliation")

    def test_quantity_outside_provider_range(self) -> None:
        response = self.client.post(
            "/v1/orders",
            headers=TOKEN,
            json=self.order_payload(quantity=1),
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_service(self) -> None:
        response = self.client.post(
            "/v1/orders",
            headers=TOKEN,
            json=self.order_payload(service_id=99999),
        )
        self.assertEqual(response.status_code, 404)

    def test_idempotency_key_is_required(self) -> None:
        payload = self.order_payload()
        payload.pop("idempotency_key")
        response = self.client.post("/v1/orders", headers=TOKEN, json=payload)
        self.assertEqual(response.status_code, 422)

    def test_order_status(self) -> None:
        response = self.client.get("/v1/orders/provider-order-1/status", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(self.provider.status_calls, 1)

    def test_order_status_requires_token(self) -> None:
        response = self.client.get("/v1/orders/provider-order-1/status")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.provider.status_calls, 0)

    def test_unknown_provider_status(self) -> None:
        response = self.client.get(
            "/v1/orders/provider-order-1/status?provider=unknown",
            headers=TOKEN,
        )
        self.assertEqual(response.status_code, 503)

    def test_duplicate_in_flight_is_rejected(self) -> None:
        slow = SlowVietnamFB()
        registry_provider = slow
        provider_registry.register(registry_provider)
        catalog = CatalogService(provider_registry)
        service = OrderService(catalog, provider_registry)

        from app.schemas import OrderCreate

        order = OrderCreate(
            service_id=1720,
            quantity=1000,
            link="https://t.me/testgroup",
            idempotency_key="same-key",
        )

        async def scenario() -> None:
            first = asyncio.create_task(service.create_order(order))
            await slow.started.wait()
            with self.assertRaises(DuplicateInFlightError):
                await service.create_order(order)
            slow.release.set()
            result = await first
            self.assertTrue(result.success)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
