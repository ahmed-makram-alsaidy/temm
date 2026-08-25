import csv
import io
import json
import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.telemetry_export import TelemetryExportService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, LatencyObservationRecord, TaskRun, UsageObservationRecord


class TelemetryExportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"export-{id(self)}"
        self.old_usage = f"old-usage-{id(self)}"
        self.new_usage = f"new-usage-{id(self)}"
        self.old_latency = f"old-latency-{id(self)}"
        self.now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_id, prompt="SECRET-PROMPT", result_output="SECRET-OUTPUT", log_output="SECRET-LOG", status="completed", selected_model_id="model", input_tokens=10, output_tokens=5, token_provenance="estimated", latency_provenance="measured", created_at=self.now, financials_json=json.dumps({"actual_cost": {"amount": "1.00", "currency": "USD", "provenance": "estimated"}, "value": {"amount": "2.00", "currency": "USD", "category": "estimated_avoided_cost", "provenance": "estimated"}})))
            session.add(UsageObservationRecord(id=self.old_usage, run_id=self.run_id, input_tokens=1, source="estimated", method="test", observed_at=self.now - timedelta(days=10)))
            session.add(UsageObservationRecord(id=self.new_usage, run_id=self.run_id, input_tokens=2, source="measured", observed_at=self.now))
            session.add(LatencyObservationRecord(id=self.old_latency, run_id=self.run_id, duration_ms=10, source="measured", observed_at=self.now - timedelta(days=10)))
            await session.commit()
        self.service = TelemetryExportService()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_type == "telemetry"))
            await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.run_id == self.run_id))
            await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.run_id == self.run_id))
            await session.execute(delete(TaskRun).where(TaskRun.id == self.run_id))
            await session.commit()

    async def test_json_and_csv_exclude_content_and_include_provenance(self):
        async with AsyncSessionLocal() as session:
            json_text = await self.service.export(session, self.now - timedelta(minutes=1), self.now + timedelta(minutes=1), "json")
            csv_text = await self.service.export(session, self.now - timedelta(minutes=1), self.now + timedelta(minutes=1), "csv")
        self.assertNotIn("SECRET-PROMPT", json_text)
        self.assertNotIn("SECRET-OUTPUT", json_text)
        payload = json.loads(json_text)
        self.assertEqual(payload["runs"][0]["actual_cost_provenance"], "estimated")
        row = list(csv.DictReader(io.StringIO(csv_text)))[0]
        self.assertEqual(row["value_category"], "estimated_avoided_cost")
        self.assertNotIn("prompt", row)

    async def test_retention_preserves_runs_and_recent_observations(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.apply_retention(session, 5, self.now)
            run = await session.get(TaskRun, self.run_id)
            old_usage = await session.get(UsageObservationRecord, self.old_usage)
            new_usage = await session.get(UsageObservationRecord, self.new_usage)
        self.assertEqual(result["usage_deleted"], 1)
        self.assertEqual(result["latency_deleted"], 1)
        self.assertIsNotNone(run)
        self.assertIsNone(old_usage)
        self.assertIsNotNone(new_usage)

    async def test_export_api_headers_and_validation(self):
        params = {"start": (self.now - timedelta(minutes=1)).isoformat(), "end": (self.now + timedelta(minutes=1)).isoformat(), "format": "csv"}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/analytics/export", params=params)
            invalid = await client.get("/api/analytics/export", params={**params, "format": "xml"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/csv")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
