import unittest

from sqlalchemy import delete

from core.ai_fleet.services.asset_library import AssetLibraryService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import (
    AssetCollectionMemberRecord,
    AssetCollectionProjectLinkRecord,
    AssetCollectionRecord,
    AssetRecord,
    ProjectRecord,
    WorkspaceRecord,
)


class AssetLibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.workspace_id = f"lib-workspace-{id(self)}"
        self.asset_id = f"lib-asset-{id(self)}"
        self.project_id = f"lib-project-{id(self)}"
        self.collection_id = None
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Library", path="D:/library", permission_profile="safe", allowed_shells="[]"))
            session.add(ProjectRecord(id=self.project_id, name="Library Project", slug=f"library-{id(self)}", project_type="design", owner="local"))
            session.add(AssetRecord(id=self.asset_id, scope_type="global", workspace_id=self.workspace_id, relative_path="logo.svg", asset_type="vector", mime_type="image/svg+xml", sha256="a" * 64, source_type="user", source_id="owner", provenance="owner_declared", size_bytes=1, state="ready"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.collection_id:
                await session.execute(delete(AssetCollectionProjectLinkRecord).where(AssetCollectionProjectLinkRecord.collection_id == self.collection_id))
                await session.execute(delete(AssetCollectionMemberRecord).where(AssetCollectionMemberRecord.collection_id == self.collection_id))
                await session.execute(delete(AssetCollectionRecord).where(AssetCollectionRecord.id == self.collection_id))
            await session.execute(delete(AssetRecord).where(AssetRecord.id == self.asset_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()

    async def test_persisted_reuse_preserves_identity_and_never_copies(self):
        first_service = AssetLibraryService()
        async with AsyncSessionLocal() as session:
            collection = await first_service.create(session, "Brand", "owner", "Approved brand assets")
            self.collection_id = collection.id
            added = await first_service.add(session, collection.id, self.asset_id)
            same = await first_service.add(session, collection.id, self.asset_id)
            linked = await first_service.link_project(session, collection.id, self.project_id)
        second_service = AssetLibraryService()
        async with AsyncSessionLocal() as session:
            detail = await second_service.detail(session, self.collection_id)
            project_collections = await second_service.list(session, self.project_id)
        self.assertFalse(added["file_copied"])
        self.assertFalse(added["file_merged"])
        self.assertTrue(added["provenance_preserved"])
        self.assertEqual(added["asset"]["sha256"], "a" * 64)
        self.assertEqual(added["asset"]["provenance"], "owner_declared")
        self.assertEqual(added["membership"]["id"], same["membership"]["id"])
        self.assertFalse(linked["file_copied"])
        self.assertEqual(detail["assets"][0]["asset"]["id"], self.asset_id)
        self.assertEqual(detail["project_links"][0]["project_id"], self.project_id)
        self.assertEqual([item["id"] for item in project_collections], [self.collection_id])


if __name__ == "__main__":
    unittest.main()
