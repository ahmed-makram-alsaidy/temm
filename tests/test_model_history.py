import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.model_lifecycle import ModelLifecycleService
from core.ai_fleet.services.pricing import PricingService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ModelPriceRecord, ModelRecord


class ModelHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"history-{id(self)}"
        self.now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            record = await ModelLifecycleService().create(session, {"id": self.model_id, "name": "History", "provider": "custom", "source_type": "user"})
            await ModelLifecycleService().update(session, self.model_id, {"description": "changed"}, record.revision)
            await PricingService().record(session, self.model_id, {"input_per_m": 1.0, "currency": "USD", "source_type": "official", "provenance": "verified", "effective_from": self.now})
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.model_id))
            await session.execute(delete(ModelPriceRecord).where(ModelPriceRecord.model_id == self.model_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == self.model_id))
            await session.commit()

    async def test_history_is_time_bounded_and_action_filterable(self):
        params = {"since": (self.now - timedelta(minutes=1)).isoformat(), "until": (self.now + timedelta(minutes=1)).isoformat()}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            history = await client.get(f"/api/models/{self.model_id}/history", params=params)
            prices = await client.get(f"/api/models/{self.model_id}/history", params={**params, "action": "model.price_recorded"})
            invalid = await client.get(f"/api/models/{self.model_id}/history", params={"since": params["until"], "until": params["since"]})
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([item["action"] for item in history.json()], ["model.created", "model.updated", "model.price_recorded"])
        self.assertTrue(all(item["created_at"] for item in history.json()))
        self.assertEqual(len(prices.json()), 1)
        self.assertEqual(prices.json()[0]["details"]["provenance"], "verified")
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
