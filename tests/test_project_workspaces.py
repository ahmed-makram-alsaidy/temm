import tempfile
import unittest
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectRecord, ProjectWorkspaceLinkRecord, WorkspaceRecord


class ProjectWorkspaceBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.folder = tempfile.TemporaryDirectory(); self.project_id = f"binding-project-{id(self)}"; self.workspace_ids = [f"binding-workspace-{id(self)}-{i}" for i in range(3)]
        roots = []
        for index in range(2): root = Path(self.folder.name) / str(index); root.mkdir(); roots.append(root)
        missing = Path(self.folder.name) / "missing"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Project", slug=f"binding-{id(self)}", purpose="", project_type="software", owner="local"))
            session.add_all([WorkspaceRecord(id=self.workspace_ids[0], name="Primary", path=str(roots[0].resolve()), permission_profile="safe", allowed_shells='["powershell"]'), WorkspaceRecord(id=self.workspace_ids[1], name="Assets", path=str(roots[1].resolve()), permission_profile="developer", allowed_shells='["powershell"]'), WorkspaceRecord(id=self.workspace_ids[2], name="Missing", path=str(missing.resolve()), permission_profile="developer", allowed_shells='["powershell"]')])
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == self.project_id)); await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id.in_(self.workspace_ids))); await session.commit()
        self.folder.cleanup()

    async def test_multiple_roots_preserve_workspace_permissions(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            primary = await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_ids[0], "role": "primary"})
            assets = await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_ids[1], "role": "assets"})
            listing = await client.get(f"/api/projects/{self.project_id}/workspaces")
            duplicate_primary = await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_ids[2], "role": "primary"})
            removed = await client.delete(f"/api/projects/{self.project_id}/workspaces/{self.workspace_ids[1]}")
        self.assertEqual(primary.status_code, 200); self.assertEqual(assets.status_code, 200)
        self.assertEqual(len(listing.json()), 2)
        profiles = {item["role"]: item["workspace"]["permission_profile"] for item in listing.json()}
        self.assertEqual(profiles, {"assets": "developer", "primary": "safe"})
        self.assertEqual(duplicate_primary.status_code, 422)
        self.assertTrue(removed.json()["removed"])

    async def test_missing_workspace_path_is_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_ids[2], "role": "secondary"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__": unittest.main()
