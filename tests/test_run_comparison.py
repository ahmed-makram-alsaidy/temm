import json
import unittest
from datetime import datetime

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.run_comparison import RunComparisonService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import LatencyObservationRecord, TaskRun, UsageObservationRecord


class RunComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_ids = [f"compare-{id(self)}-{index}" for index in range(2)]
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_ids[0], prompt="a", status="completed", quality_eval_score=None, quality_provenance="unknown", financials_json=json.dumps({"actual_cost": {"amount": "1.00", "currency": "USD", "provenance": "estimated"}, "value": {"amount": "2.00", "currency": "USD", "provenance": "estimated", "category": "estimated_avoided_cost"}})))
            session.add(TaskRun(id=self.run_ids[1], prompt="b", status="completed", quality_eval_score=90, quality_provenance="measured", financials_json=json.dumps({"actual_cost": {"amount": "2.00", "currency": "EUR", "provenance": "estimated"}, "value": {"amount": "3.00", "currency": "EUR", "provenance": "estimated", "category": "equivalent_api_value"}})))
            session.add_all([
                LatencyObservationRecord(id=f"latency-{id(self)}-0", run_id=self.run_ids[0], duration_ms=100, source="measured", observed_at=now),
                LatencyObservationRecord(id=f"latency-{id(self)}-1", run_id=self.run_ids[1], duration_ms=200, source="measured", observed_at=now),
                UsageObservationRecord(id=f"usage-{id(self)}-0", run_id=self.run_ids[0], input_tokens=10, source="estimated", method="test", observed_at=now),
                UsageObservationRecord(id=f"usage-{id(self)}-1", run_id=self.run_ids[1], input_tokens=20, source="provider_reported", observed_at=now),
            ])
            await session.commit()
        self.service = RunComparisonService()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.run_id.in_(self.run_ids)))
            await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.run_id.in_(self.run_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            await session.commit()

    async def test_only_commensurable_metrics_are_marked_comparable(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.compare(session, self.run_ids)
        self.assertTrue(result["metrics"]["duration_ms"]["comparable"])
        self.assertEqual(result["metrics"]["duration_ms"]["reason"], "commensurable")
        self.assertFalse(result["metrics"]["input_tokens"]["comparable"])
        self.assertEqual(result["metrics"]["input_tokens"]["reason"], "incompatible_provenance")
        self.assertEqual(result["metrics"]["actual_cost"]["reason"], "incompatible_currency")
        self.assertEqual(result["metrics"]["value"]["reason"], "incompatible_currency")
        self.assertEqual(result["metrics"]["quality"]["reason"], "missing_or_unknown_value")

    async def test_api_and_distinct_run_validation(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            valid = await client.get("/api/runs/compare", params=[("run_id", self.run_ids[0]), ("run_id", self.run_ids[1])])
            invalid = await client.get("/api/runs/compare", params=[("run_id", self.run_ids[0]), ("run_id", self.run_ids[0])])
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
