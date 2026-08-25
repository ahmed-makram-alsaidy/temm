import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.project_brain import ProjectBrainService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectBrainFactRecord, ProjectBrainFactRevisionRecord, ProjectRecord


class ProjectBrainRevisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"revision-project-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Revision", slug=f"revision-{id(self)}", project_type="software", owner="local")); await session.commit()
            first = await ProjectBrainService().merge(session, self.project_id, {"section": "architecture", "fact_key": "database", "value": "SQLite", "truth_state": "confirmed", "provenance": "owner_declared", "source_type": "user", "source_id": "owner", "confidence": 1})
            self.fact_id = first.id
            await ProjectBrainService().merge(session, self.project_id, {"section": "architecture", "fact_key": "database", "value": "PostgreSQL", "truth_state": "confirmed", "provenance": "owner_declared", "source_type": "user", "source_id": "owner", "confidence": 1}, 1)
        self.transport = httpx.ASGITransport(app=app)
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == self.fact_id)); await session.execute(delete(ProjectBrainFactRecord).where(ProjectBrainFactRecord.id == self.fact_id)); await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_list_diff_and_restore_creates_new_revision(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            revisions = await client.get(f"/api/projects/brain/facts/{self.fact_id}/revisions")
            diff = await client.get(f"/api/projects/brain/facts/{self.fact_id}/diff", params={"from_revision": 1, "to_revision": 2})
            restored = await client.post(f"/api/projects/brain/facts/{self.fact_id}/restore", json={"revision": 1, "expected_revision": 2})
            after = await client.get(f"/api/projects/brain/facts/{self.fact_id}/revisions")
        self.assertEqual([item["revision"] for item in revisions.json()], [1, 2])
        self.assertEqual(diff.json()["changes"]["value"], {"before": "SQLite", "after": "PostgreSQL"})
        self.assertEqual(restored.json()["value"], "SQLite"); self.assertEqual(restored.json()["revision"], 3)
        self.assertEqual([item["revision"] for item in after.json()], [1, 2, 3])
        self.assertEqual(after.json()[1]["snapshot"]["value"], "PostgreSQL")

    async def test_stale_restore_is_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post(f"/api/projects/brain/facts/{self.fact_id}/restore", json={"revision": 1, "expected_revision": 1})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__": unittest.main()
