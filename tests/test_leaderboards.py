import json
import unittest
from datetime import datetime

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.benchmark_suites import BenchmarkSuiteService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, BenchmarkCaseRecord, BenchmarkSuiteVersionRecord, ModelRecord, TaskRun


class PersonalLeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.suite_key = f"leaderboard-{id(self)}"
        self.model_ids = [f"owned-a-{id(self)}", f"owned-b-{id(self)}", f"catalog-{id(self)}"]
        self.run_ids = []
        async with AsyncSessionLocal() as session:
            self.version = await BenchmarkSuiteService().create_version(session, {"suite_key": self.suite_key, "name": "Leaderboard", "category": "coding", "provenance": "user_authored", "cases": [{"case_key": "one", "prompt": "x", "expected_behavior": "x", "evaluator_type": "exact"}]})
            session.add_all([ModelRecord(id=self.model_ids[0], name="Owned A", provider="custom", source_type="user"), ModelRecord(id=self.model_ids[1], name="Owned B", provider="local", source_type="runtime"), ModelRecord(id=self.model_ids[2], name="Catalog", provider="catalog", source_type="catalog", registry_state="catalog")])
            now = datetime.utcnow()
            for index, (model, score, provenance) in enumerate([(self.model_ids[0], 90, "measured"), (self.model_ids[0], 100, "measured"), (self.model_ids[1], 92, "measured"), (self.model_ids[2], 100, "measured"), (self.model_ids[1], None, "unknown")]):
                run_id = f"leaderboard-run-{id(self)}-{index}"; self.run_ids.append(run_id)
                session.add(TaskRun(id=run_id, prompt="x", status="completed", selected_model_id=model, quality_eval_score=score, quality_provenance=provenance, completed_at=now, measurement_metadata=json.dumps({"benchmark": {"suite_version_id": self.version.id, "content_hash": self.version.content_hash}})))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            await session.execute(delete(ModelRecord).where(ModelRecord.id.in_(self.model_ids)))
            await session.execute(delete(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id == self.version.id))
            await session.execute(delete(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.id == self.version.id))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.suite_key))
            await session.commit()

    async def test_ranks_only_owned_comparable_measured_evidence(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/benchmarks/leaderboard", params={"suite_version_id": self.version.id, "category": "coding"})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["rows"]
        self.assertEqual([row["model_id"] for row in rows], self.model_ids[:2])
        self.assertEqual(rows[0]["score"], 95.0)
        self.assertEqual(rows[0]["sample_size"], 2)
        self.assertEqual(rows[0]["provenance"], "measured")
        self.assertEqual(rows[1]["score"], 92.0)
        self.assertNotIn(self.model_ids[2], [row["model_id"] for row in rows])


if __name__ == "__main__":
    unittest.main()
