import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.pricing import PricingService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelPriceRecord, ModelRecord


class PricingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"price-model-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Price Model", provider="custom", source_type="user"))
            await session.commit()
        self.service = PricingService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ModelPriceRecord).where(ModelPriceRecord.model_id == self.model_id))
            model = await session.get(ModelRecord, self.model_id)
            if model:
                await session.delete(model)
            await session.commit()

    async def test_historical_price_resolution_and_current_projection(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            historical = await self.service.record(session, self.model_id, {
                "currency": "USD", "input_per_m": 1.0, "output_per_m": 2.0,
                "source_type": "official", "source_uri": "https://example.invalid/pricing",
                "provenance": "verified", "confidence": "high",
                "effective_from": now - timedelta(days=10), "effective_to": now - timedelta(days=5),
            })
            current = await self.service.record(session, self.model_id, {
                "currency": "USD", "input_per_m": 3.0, "output_per_m": 4.0,
                "source_type": "provider", "provenance": "provider_reported", "confidence": "high",
                "effective_from": now - timedelta(days=5), "effective_to": None,
            })
            resolved_old = await self.service.resolve(session, self.model_id, now - timedelta(days=7))
            resolved_current = await self.service.resolve(session, self.model_id, now)
            compatible = await self.service.resolve(session, self.model_id, now, required_dimensions={"input", "output"})
            incompatible = await self.service.resolve(session, self.model_id, now, required_dimensions={"cache"})
            model = await session.get(ModelRecord, self.model_id)
        self.assertEqual(resolved_old.id, historical.id)
        self.assertEqual(resolved_current.id, current.id)
        self.assertEqual(compatible.id, current.id)
        self.assertIsNone(incompatible)
        self.assertEqual(model.input_cost_per_m, 3.0)
        self.assertEqual(model.pricing_provenance, "provider_reported")

    async def test_user_declared_price_is_retained_but_not_trusted_for_resolution(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            record = await self.service.record(session, self.model_id, {
                "currency": "USD", "input_per_m": 1.0, "source_type": "user",
                "provenance": "user_declared", "confidence": "low", "effective_from": now,
            })
            resolved = await self.service.resolve(session, self.model_id, now + timedelta(seconds=1))
            model = await session.get(ModelRecord, self.model_id)
        self.assertEqual(record.provenance, "user_declared")
        self.assertIsNone(resolved)
        self.assertEqual(model.pricing_provenance, "unknown")

    async def test_overlapping_and_invalid_prices_are_rejected(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            await self.service.record(session, self.model_id, {
                "currency": "USD", "input_per_m": 1.0, "source_type": "official",
                "provenance": "verified", "effective_from": now,
            })
            with self.assertRaises(Exception):
                await self.service.record(session, self.model_id, {
                    "currency": "USD", "output_per_m": 1.0, "source_type": "official",
                    "provenance": "verified", "effective_from": now + timedelta(days=1),
                })


class PricingApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"price-api-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Price API", provider="custom"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ModelPriceRecord).where(ModelPriceRecord.model_id == self.model_id))
            model = await session.get(ModelRecord, self.model_id)
            if model:
                await session.delete(model)
            await session.commit()

    async def test_price_api_validates_and_lists_history(self):
        now = datetime.utcnow().isoformat()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            invalid = await client.post(f"/api/models/{self.model_id}/prices", json={"currency": "US", "source_type": "official", "provenance": "verified", "effective_from": now})
            created = await client.post(f"/api/models/{self.model_id}/prices", json={"currency": "USD", "input_per_m": 0.5, "source_type": "official", "provenance": "verified", "confidence": "high", "effective_from": now})
            history = await client.get(f"/api/models/{self.model_id}/prices")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(history.json()[0]["provenance"], "verified")


if __name__ == "__main__":
    unittest.main()
