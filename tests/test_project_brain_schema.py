import json
import unittest

from sqlalchemy import delete, inspect

from core.ai_fleet.storage.database import AsyncSessionLocal, engine, init_db
from core.ai_fleet.storage.models import ProjectBrainFactRecord, ProjectBrainFactRevisionRecord, ProjectRecord


class ProjectBrainSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): await init_db(); self.project_id = f"brain-project-{id(self)}"; self.fact_id = f"brain-fact-{id(self)}"
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == self.fact_id)); await session.execute(delete(ProjectBrainFactRecord).where(ProjectBrainFactRecord.id == self.fact_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_structured_fact_retains_truth_source_and_revision(self):
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Brain", slug=f"brain-{id(self)}", project_type="software", owner="local"))
            fact = ProjectBrainFactRecord(id=self.fact_id, project_id=self.project_id, section="architecture", fact_key="database", value_json=json.dumps({"engine": "sqlite", "required": True}), truth_state="confirmed", provenance="owner_declared", source_type="user", source_id="local_owner", confidence=1.0, revision=1)
            session.add(fact); session.add(ProjectBrainFactRevisionRecord(id=f"revision-{id(self)}", fact_id=self.fact_id, revision=1, snapshot_json=json.dumps(fact.to_dict()))); await session.commit()
        payload = fact.to_dict(); self.assertEqual(payload["value"]["engine"], "sqlite"); self.assertEqual(payload["truth_state"], "confirmed"); self.assertEqual(payload["provenance"], "owner_declared")
        async with engine.connect() as connection:
            columns = await connection.run_sync(lambda sync: {item["name"] for item in inspect(sync).get_columns("project_brain_facts")})
        self.assertFalse({"chat", "prompt", "content", "blob"} & columns)
        self.assertTrue({"section", "fact_key", "value_json", "truth_state", "provenance", "source_type", "revision"} <= columns)


if __name__ == "__main__": unittest.main()
