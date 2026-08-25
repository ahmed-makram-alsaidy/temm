import json
import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.analytics import AnalyticsService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import TaskRun, UsageObservationRecord


class AnalyticsAggregationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_ids = [f"analytics-{id(self)}-{index}" for index in range(2)]
        self.usage_id = f"analytics-usage-{id(self)}"
        self.now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_ids[0], prompt="one", status="completed", fallback_chain='["a","b"]', created_at=self.now, financials_json=json.dumps({"actual_cost": {"amount": "1.25", "currency": "USD", "provenance": "provider_reported"}, "value": {"category": "direct_saving", "amount": "0.75"}})))
            session.add(TaskRun(id=self.run_ids[1], prompt="two", status="failed", created_at=self.now, financials_json=json.dumps({"actual_cost": {"amount": None, "provenance": "unknown"}, "value": {"category": "estimated_avoided_cost", "amount": None}})))
            session.add(UsageObservationRecord(id=self.usage_id, run_id=self.run_ids[0], input_tokens=100, output_tokens=20, source="provider_reported", observed_at=self.now))
            await session.commit()
        self.service = AnalyticsService()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.id == self.usage_id))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            await session.commit()

    async def test_aggregation_preserves_provenance_and_taxonomy(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.aggregate(session, self.now - timedelta(minutes=1), self.now + timedelta(minutes=1))
        self.assertEqual(result["runs"]["statuses"], {"completed": 1, "failed": 1})
        self.assertEqual(result["runs"]["fallback_runs"], 1)
        self.assertEqual(result["usage_by_provenance"]["provider_reported"]["input_tokens"], 100)
        self.assertEqual(result["financials"]["provider_reported_actual_cost"], "1.25")
        self.assertEqual(result["financials"]["direct_saving"], "0.75")
        self.assertEqual(result["financials"]["unknown_actual_cost_runs"], 1)

    async def test_api_requires_bounded_valid_range(self):
        start = (self.now - timedelta(minutes=1)).isoformat()
        end = (self.now + timedelta(minutes=1)).isoformat()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            valid = await client.get("/api/analytics/summary", params={"start": start, "end": end})
            invalid = await client.get("/api/analytics/summary", params={"start": end, "end": start})
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
