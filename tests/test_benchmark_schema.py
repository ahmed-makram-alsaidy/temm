import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, BenchmarkCaseRecord, BenchmarkSuiteVersionRecord


class VersionedBenchmarkSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.suite_key = f"suite-{id(self)}"
        self.version_ids = []
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.version_ids:
                await session.execute(delete(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id.in_(self.version_ids)))
                await session.execute(delete(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.id.in_(self.version_ids)))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.suite_key))
            await session.commit()

    def payload(self, expected="Returns valid JSON"):
        return {"suite_key": self.suite_key, "name": "JSON benchmark", "category": "coding", "provenance": "user_authored", "cases": [{"case_key": "case-1", "prompt": "Return JSON", "expected_behavior": expected, "evaluator_type": "json_schema", "evaluator_config": {"type": "object"}, "category": "coding", "difficulty": "medium", "weight": 2, "provenance": "user_authored"}]}

    async def test_identical_dataset_reuses_version_and_change_creates_next(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            first = await client.post("/api/benchmarks/suites/versions", json=self.payload())
            same = await client.post("/api/benchmarks/suites/versions", json=self.payload())
            changed = await client.post("/api/benchmarks/suites/versions", json=self.payload("Returns JSON object with id"))
            versions = await client.get(f"/api/benchmarks/suites/{self.suite_key}/versions")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["id"], same.json()["id"])
        self.assertEqual(first.json()["version"], 1)
        self.assertEqual(changed.json()["version"], 2)
        self.version_ids = [first.json()["id"], changed.json()["id"]]
        self.assertEqual([item["version"] for item in versions.json()], [2, 1])

    async def test_case_contract_and_invalid_evaluator(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/benchmarks/suites/versions", json=self.payload())
            self.assertEqual(created.status_code, 200, created.text)
            self.version_ids = [created.json()["id"]]
            cases = await client.get(f"/api/benchmarks/versions/{self.version_ids[0]}/cases")
            invalid_payload = self.payload()
            invalid_payload["cases"][0]["evaluator_type"] = "magic_score"
            invalid = await client.post("/api/benchmarks/suites/versions", json=invalid_payload)
        self.assertEqual(cases.json()[0]["weight"], 2.0)
        self.assertEqual(cases.json()[0]["expected_behavior"], "Returns valid JSON")
        self.assertEqual(cases.json()[0]["provenance"], "user_authored")
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
