import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelPriceRecord, ModelRecord, SystemSetting


class BaselineIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"baseline-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Baseline Candidate", provider="custom"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ModelPriceRecord).where(ModelPriceRecord.model_id == self.model_id))
            model = await session.get(ModelRecord, self.model_id)
            if model:
                await session.delete(model)
            setting = await session.get(SystemSetting, "reference_baseline_model")
            if setting and setting.value == self.model_id:
                setting.value = "gpt-4o"
            await session.commit()

    async def test_unpriced_model_cannot_be_baseline(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.patch(f"/api/models/{self.model_id}/set-baseline")
        self.assertEqual(response.status_code, 409)

    async def test_current_trusted_price_allows_baseline(self):
        now = datetime.utcnow().isoformat()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            price = await client.post(f"/api/models/{self.model_id}/prices", json={"currency": "USD", "input_per_m": 1, "output_per_m": 2, "source_type": "official", "provenance": "verified", "effective_from": now})
            baseline = await client.patch(f"/api/models/{self.model_id}/set-baseline")
            status = await client.get("/api/models/baseline/status")
        self.assertEqual(price.status_code, 200)
        self.assertEqual(baseline.status_code, 200)
        self.assertTrue(status.json()["available"])
        self.assertEqual(status.json()["model"]["id"], self.model_id)

    async def test_expired_price_does_not_support_baseline(self):
        start = datetime.utcnow() - timedelta(days=2)
        end = datetime.utcnow() - timedelta(days=1)
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            await client.post(f"/api/models/{self.model_id}/prices", json={"currency": "USD", "input_per_m": 1, "source_type": "official", "provenance": "verified", "effective_from": start.isoformat(), "effective_to": end.isoformat()})
            response = await client.patch(f"/api/models/{self.model_id}/set-baseline")
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
