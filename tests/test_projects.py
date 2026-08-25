import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectRecord, TaskRun


class ProjectServiceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): await init_db(); self.project_id = None; self.run_id = f"project-run-{id(self)}"; self.transport = httpx.ASGITransport(app=app)
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TaskRun).where(TaskRun.id == self.run_id))
            if self.project_id:
                await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_crud_archive_restore_and_history_policy(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/projects", json={"name": "Clinic", "slug": f"clinic-{id(self)}", "purpose": "Operations", "project_type": "business_system"})
            self.assertEqual(created.status_code, 200, created.text); self.project_id = created.json()["id"]
            revision = created.json()["revision"]
            updated = await client.patch(f"/api/projects/{self.project_id}", json={"expected_revision": revision, "purpose": "Updated operations"})
            stale = await client.patch(f"/api/projects/{self.project_id}", json={"expected_revision": revision, "purpose": "stale"})
            async with AsyncSessionLocal() as session: session.add(TaskRun(id=self.run_id, prompt="x", project_id=self.project_id, status="completed")); await session.commit()
            archived = await client.post(f"/api/projects/{self.project_id}/archive")
            active_list = await client.get("/api/projects")
            all_list = await client.get("/api/projects", params={"include_archived": True})
            removed = await client.delete(f"/api/projects/{self.project_id}")
            restored = await client.post(f"/api/projects/{self.project_id}/restore")
        self.assertEqual(updated.json()["purpose"], "Updated operations")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(archived.json()["lifecycle_status"], "archived")
        self.assertFalse(any(item["id"] == self.project_id for item in active_list.json()))
        self.assertTrue(any(item["id"] == self.project_id for item in all_list.json()))
        self.assertEqual(removed.status_code, 409)
        self.assertEqual(restored.json()["id"], self.project_id)
        async with AsyncSessionLocal() as session: self.assertIsNotNone(await session.get(TaskRun, self.run_id))

    async def test_duplicate_slug_and_invalid_type_are_rejected(self):
        slug = f"duplicate-{id(self)}"
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            first = await client.post("/api/projects", json={"name": "One", "slug": slug, "purpose": "Build the first project outcome", "project_type": "software"})
            self.project_id = first.json()["id"]
            duplicate = await client.post("/api/projects", json={"name": "Two", "slug": slug, "purpose": "Build another outcome", "project_type": "software"})
            invalid = await client.post("/api/projects", json={"name": "Bad", "slug": f"bad-{id(self)}", "purpose": "Build an invalid project", "project_type": "magic"})
        self.assertEqual(duplicate.status_code, 409); self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__": unittest.main()
