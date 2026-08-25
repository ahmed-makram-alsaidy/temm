import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.capability_evidence import CapabilityEvidenceService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelCapabilityEvidenceRecord, ModelRecord


class CapabilityEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"cap-model-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Capability Model", provider="custom"))
            await session.commit()
        self.service = CapabilityEvidenceService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))
            model = await session.get(ModelRecord, self.model_id)
            if model:
                await session.delete(model)
            await session.commit()

    async def test_precedence_conflict_and_expiry(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            await self.service.record(session, self.model_id, {"capability": "coding", "supported": False, "score": None, "provenance": "user_declared", "source_type": "user", "observed_at": now})
            measured = await self.service.record(session, self.model_id, {"capability": "coding", "supported": True, "score": 91, "provenance": "benchmark_measured", "source_type": "benchmark", "observed_at": now})
            await self.service.record(session, self.model_id, {"capability": "image_input", "supported": True, "score": 80, "provenance": "provider_reported", "source_type": "provider", "observed_at": now - timedelta(days=2), "expires_at": now - timedelta(days=1)})
            aggregate = await self.service.aggregate(session, self.model_id, at=now)
        self.assertTrue(aggregate["resolved"]["coding"]["supported"])
        self.assertEqual(aggregate["resolved"]["coding"]["evidence_id"], measured.id)
        self.assertEqual(aggregate["resolved"]["coding"]["score"], 91)
        self.assertTrue(aggregate["conflicts"])
        self.assertNotIn("image_input", aggregate["resolved"])

    async def test_invalid_score_is_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception):
                await self.service.record(session, self.model_id, {"capability": "coding", "supported": False, "score": 50, "provenance": "user_declared", "source_type": "user", "observed_at": datetime.utcnow()})


class CapabilityEvidenceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"cap-api-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Capability API", provider="custom"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))
            model = await session.get(ModelRecord, self.model_id)
            if model:
                await session.delete(model)
            await session.commit()

    async def test_public_api_accepts_user_evidence_but_rejects_measured_forgery(self):
        now = datetime.utcnow().isoformat()
        base = {"capability": "coding", "supported": True, "score": 75, "source_type": "user", "observed_at": now}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post(f"/api/models/{self.model_id}/capabilities", json={**base, "provenance": "user_declared"})
            forged = await client.post(f"/api/models/{self.model_id}/capabilities", json={**base, "provenance": "benchmark_measured", "source_type": "benchmark"})
            aggregate = await client.get(f"/api/models/{self.model_id}/capabilities")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(aggregate.json()["resolved"]["coding"]["provenance"], "user_declared")


if __name__ == "__main__":
    unittest.main()
