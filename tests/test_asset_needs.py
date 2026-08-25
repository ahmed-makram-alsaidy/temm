import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.services.asset_needs import AssetNeedService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AssetRecord, AssetUsageRecord, ProjectNeedRecord, ProjectRecord, WorkspaceRecord


class AssetNeedScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_id = f"need-project-{id(self)}"
        self.workspace_id = f"need-workspace-{id(self)}"
        self.asset_ids = [f"need-asset-{id(self)}-{index}" for index in range(2)]
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Needs", slug=f"asset-needs-{id(self)}", project_type="design", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Assets", path=str(self.root.resolve()), permission_profile="safe", allowed_shells="[]"))
            session.add(AssetRecord(id=self.asset_ids[0], scope_type="project", project_id=self.project_id, workspace_id=self.workspace_id, relative_path="missing.svg", asset_type="vector", mime_type="image/svg+xml", sha256="a" * 64, source_type="user", provenance="owner_declared", size_bytes=1, state="missing"))
            session.add(AssetRecord(id=self.asset_ids[1], scope_type="project", project_id=self.project_id, workspace_id=self.workspace_id, relative_path="optional.svg", asset_type="vector", mime_type="image/svg+xml", sha256="b" * 64, source_type="user", provenance="owner_declared", size_bytes=1, state="missing"))
            session.add(AssetUsageRecord(id=f"usage-{id(self)}-0", asset_id=self.asset_ids[0], target_type="component", target_id="header", usage_role="logo", required=True))
            session.add(AssetUsageRecord(id=f"usage-{id(self)}-1", asset_id=self.asset_ids[1], target_type="component", target_id="footer", usage_role="decoration", required=False))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))
            await session.execute(delete(AssetUsageRecord).where(AssetUsageRecord.asset_id.in_(self.asset_ids)))
            await session.execute(delete(AssetRecord).where(AssetRecord.id.in_(self.asset_ids)))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.temp.cleanup()

    async def test_required_missing_asset_creates_deduplicated_blocking_need(self):
        service = AssetNeedService()
        async with AsyncSessionLocal() as session:
            first = await service.derive(session, self.project_id)
            second = await service.derive(session, self.project_id)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].id, second[0].id)
        payload = first[0].to_dict()
        self.assertEqual(payload["blocked_nodes"], ["header"])
        self.assertEqual(payload["source_type"], "asset_usage")
        self.assertEqual(payload["impact"], "blocking")
        self.assertIn("approved_license_required", first[0].description)


if __name__ == "__main__":
    unittest.main()
