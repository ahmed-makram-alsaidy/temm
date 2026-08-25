import json
import tempfile
import unittest
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, BenchmarkCaseRecord, BenchmarkSuiteVersionRecord, WorkspaceRecord


class BenchmarkPackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.workspace_id = f"pack-workspace-{id(self)}"
        self.suite_key = f"pack-{id(self)}"
        self.version_ids = []
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Packs", path=str(self.root.resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.version_ids:
                await session.execute(delete(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id.in_(self.version_ids)))
                await session.execute(delete(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.id.in_(self.version_ids)))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.suite_key))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()

    def payload(self):
        return {"suite_key": self.suite_key, "name": "Pack", "category": "coding", "provenance": "user_authored", "cases": [{"case_key": "one", "prompt": "Return JSON", "expected_behavior": "Valid JSON", "evaluator_type": "json_schema", "evaluator_config": {"type": "object"}, "category": "coding", "difficulty": "easy", "weight": 1}]}

    async def test_json_import_and_yaml_export_round_trip(self):
        (self.root / "pack.json").write_text(json.dumps(self.payload()), encoding="utf-8")
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            imported = await client.post("/api/benchmarks/packs/import", json={"workspace_id": self.workspace_id, "path": "pack.json"})
            self.assertEqual(imported.status_code, 200, imported.text)
            self.version_ids = [imported.json()["id"]]
            exported = await client.get(f"/api/benchmarks/versions/{self.version_ids[0]}/export", params={"format": "yaml"})
        self.assertEqual(imported.json()["provenance"], "imported")
        self.assertIn("expected_behavior: Valid JSON", exported.text)
        self.assertIn("content_hash:", exported.text)
        self.assertEqual(exported.headers["content-type"].split(";")[0], "application/yaml")

    async def test_traversal_malformed_and_deep_packs_are_rejected(self):
        outside = self.root.parent / f"outside-{id(self)}.json"
        outside.write_text(json.dumps(self.payload()), encoding="utf-8")
        (self.root / "bad.yaml").write_text("cases: [", encoding="utf-8")
        nested = value = {}
        for _ in range(14):
            value["x"] = {}
            value = value["x"]
        (self.root / "deep.json").write_text(json.dumps(nested), encoding="utf-8")
        try:
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                traversal = await client.post("/api/benchmarks/packs/import", json={"workspace_id": self.workspace_id, "path": str(outside)})
                malformed = await client.post("/api/benchmarks/packs/import", json={"workspace_id": self.workspace_id, "path": "bad.yaml"})
                deep = await client.post("/api/benchmarks/packs/import", json={"workspace_id": self.workspace_id, "path": "deep.json"})
            self.assertEqual(traversal.status_code, 422)
            self.assertEqual(malformed.status_code, 422)
            self.assertEqual(deep.status_code, 422)
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
