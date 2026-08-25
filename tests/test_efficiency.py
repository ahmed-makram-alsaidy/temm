import json
import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.efficiency import EfficiencyService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import TaskRun, UsageObservationRecord


class EfficiencyMetricTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"efficiency-{id(self)}"
        self.usage_id = f"efficiency-usage-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_id, prompt="x", status="completed", quality_eval_score=80, quality_provenance="measured", financials_json=json.dumps({"actual_cost": {"amount": "2.00", "currency": "USD", "provenance": "estimated"}})))
            session.add(UsageObservationRecord(id=self.usage_id, run_id=self.run_id, input_tokens=1500, output_tokens=500, source="provider_reported", observed_at=__import__("datetime").datetime.utcnow()))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.id == self.usage_id))
            await session.execute(delete(TaskRun).where(TaskRun.id == self.run_id))
            await session.commit()

    async def test_formula_retains_uncertainty_and_currency(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get(f"/api/runs/{self.run_id}/efficiency")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["quality_per_1k_tokens"]["value"], "40.0000")
        self.assertEqual(payload["quality_per_1k_tokens"]["token_provenance"], ["provider_reported"])
        self.assertEqual(payload["quality_per_currency_unit"]["value"], "40.0000")
        self.assertEqual(payload["quality_per_currency_unit"]["cost_provenance"], "estimated")
        self.assertEqual(payload["quality_per_currency_unit"]["currency"], "USD")

    def test_missing_and_zero_evidence_excludes_metrics(self):
        service = EfficiencyService()
        unknown_quality = TaskRun(id="a", prompt="x", quality_eval_score=None, quality_provenance="unknown")
        self.assertEqual(service.calculate(unknown_quality, {"usage": {}, "provenance": {}})["exclusions"]["quality"], "quality_unavailable")
        zero = TaskRun(id="b", prompt="x", quality_eval_score=90, quality_provenance="measured", financials_json=json.dumps({"actual_cost": {"amount": "0", "currency": "USD", "provenance": "provider_reported"}}))
        result = service.calculate(zero, {"usage": {"input_tokens": 0}, "provenance": {"input_tokens": "measured"}})
        self.assertEqual(result["exclusions"]["quality_per_1k_tokens"], "zero_token_denominator")
        self.assertEqual(result["exclusions"]["quality_per_currency_unit"], "zero_cost_denominator")


if __name__ == "__main__":
    unittest.main()
