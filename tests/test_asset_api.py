import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.asset_library import AssetLibraryService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AssetCollectionMemberRecord, AssetCollectionProjectLinkRecord, AssetCollectionRecord, AssetRecord, ProjectRecord, WorkspaceRecord


class AssetApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"asset-api-project-{id(self)}"
        self.workspace_id = f"asset-api-workspace-{id(self)}"
        self.asset_id = f"asset-api-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Assets", slug=f"asset-api-{id(self)}", project_type="design", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Assets", path="D:/asset-api", permission_profile="safe", allowed_shells="[]"))
            session.add(AssetRecord(id=self.asset_id, scope_type="project", project_id=self.project_id, workspace_id=self.workspace_id, relative_path="document.pdf", asset_type="document", mime_type="application/pdf", sha256="a" * 64, source_type="user", provenance="owner_declared", size_bytes=10, state="ready"))
            await session.commit()
            collection = await AssetLibraryService().create(session, "Documents", "owner")
            self.collection_id = collection.id
            await AssetLibraryService().add(session, collection.id, self.asset_id)
            await AssetLibraryService().link_project(session, collection.id, self.project_id)
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AssetCollectionProjectLinkRecord).where(AssetCollectionProjectLinkRecord.collection_id == self.collection_id))
            await session.execute(delete(AssetCollectionMemberRecord).where(AssetCollectionMemberRecord.collection_id == self.collection_id))
            await session.execute(delete(AssetCollectionRecord).where(AssetCollectionRecord.id == self.collection_id))
            await session.execute(delete(AssetRecord).where(AssetRecord.id == self.asset_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()

    async def test_project_asset_and_library_contracts_include_evidence(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            listing = await client.get("/api/assets", params={"project_id": self.project_id})
            detail = await client.get(f"/api/assets/{self.asset_id}")
            library = await client.get("/api/asset-library", params={"project_id": self.project_id})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["asset_type"], "document")
        self.assertIn("validation", detail.json())
        self.assertIn("usage", detail.json())
        self.assertIn("variants", detail.json())
        self.assertEqual(library.json()[0]["assets"][0]["asset"]["id"], self.asset_id)


if __name__ == "__main__":
    unittest.main()
