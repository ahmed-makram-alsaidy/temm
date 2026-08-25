import base64
import unittest
import uuid

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.ai_fleet.main import app
from core.ai_fleet.api import routes
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import PluginCatalogSourceRecord


class PluginMarketplaceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.source_id = f"api-market-{uuid.uuid4().hex[:8]}"
        key = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.payload = {"source_id": self.source_id, "index_url": "https://catalog.example.test/index.json", "public_key": base64.b64encode(key).decode()}
        self.original_safety = routes.plugin_marketplace_service.safety
        routes.plugin_marketplace_service.safety = __import__("core.ai_fleet.url_safety", fromlist=["UrlSafetyService"]).UrlSafetyService(lambda host: ["93.184.216.34"])
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        routes.plugin_marketplace_service.safety = self.original_safety
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            if source:
                await session.delete(source)
                await session.commit()

    async def test_source_is_disabled_by_default_and_catalog_stays_empty(self):
        created = await self.client.post("/api/plugins/marketplace/sources", json=self.payload)
        self.assertEqual(created.status_code, 200)
        self.assertFalse(created.json()["enabled"])
        sources = await self.client.get("/api/plugins/marketplace/sources")
        source = next(item for item in sources.json() if item["id"] == self.source_id)
        self.assertEqual(source["last_state"], "never_refreshed")
        catalog = await self.client.get("/api/plugins/marketplace/catalog")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json(), [])

    async def test_enable_is_explicit_and_disable_clears_cached_catalog(self):
        await self.client.post("/api/plugins/marketplace/sources", json=self.payload)
        enabled = await self.client.patch(f"/api/plugins/marketplace/sources/{self.source_id}", json={"enabled": True})
        self.assertTrue(enabled.json()["enabled"])
        disabled = await self.client.patch(f"/api/plugins/marketplace/sources/{self.source_id}", json={"enabled": False})
        self.assertFalse(disabled.json()["enabled"])
        self.assertEqual(disabled.json()["last_state"], "disabled")


if __name__ == "__main__":
    unittest.main()
