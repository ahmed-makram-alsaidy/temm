import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, inspect

from core.ai_fleet.storage.database import AsyncSessionLocal, engine, init_db
from core.ai_fleet.storage.models import ProjectRecord, ProjectWorkspaceLinkRecord, WorkspaceRecord


class ProjectIdentitySchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.folder = tempfile.TemporaryDirectory(); self.project_id = f"project-{id(self)}"; self.workspace_ids = [f"project-workspace-{id(self)}-{i}" for i in range(2)]

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == self.project_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id.in_(self.workspace_ids)))
            await session.commit()
        self.folder.cleanup()

    async def test_project_is_distinct_from_workspace_and_supports_links(self):
        roots = []
        for index in range(2): root = Path(self.folder.name) / str(index); root.mkdir(); roots.append(root)
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Clinic CRM", slug=f"clinic-crm-{id(self)}", purpose="Manage clinic operations", project_type="business_system", owner="local_owner"))
            for index, workspace_id in enumerate(self.workspace_ids):
                session.add(WorkspaceRecord(id=workspace_id, name=f"Root {index}", path=str(roots[index].resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
                session.add(ProjectWorkspaceLinkRecord(id=f"link-{id(self)}-{index}", project_id=self.project_id, workspace_id=workspace_id, role="primary" if index == 0 else "secondary"))
            await session.commit()
            project = await session.get(ProjectRecord, self.project_id)
        payload = project.to_dict()
        self.assertEqual(payload["purpose"], "Manage clinic operations")
        self.assertNotIn("path", payload)
        async with engine.connect() as connection:
            columns = await connection.run_sync(lambda sync: {item["name"] for item in inspect(sync).get_columns("projects")})
        self.assertNotIn("path", columns)
        self.assertNotIn("workspace_id", columns)


if __name__ == "__main__": unittest.main()
