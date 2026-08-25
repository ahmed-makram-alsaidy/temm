import hashlib
import struct
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AssetRecord, AssetTransformJobRecord, WorkspaceRecord


def png():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"\x00\xff\x00\x00" * 2
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class MediaTransformApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name).resolve()
        (self.root / "variants").mkdir()
        content = png()
        (self.root / "source.png").write_bytes(content)
        suffix = uuid.uuid4().hex[:8]
        self.workspace_id = f"media-api-workspace-{suffix}"
        self.asset_id = f"media-api-asset-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Media API", path=str(self.root), permission_profile="developer", allowed_shells="[]"))
            session.add(AssetRecord(id=self.asset_id, scope_type="global", workspace_id=self.workspace_id, relative_path="source.png", asset_type="raster", mime_type="image/png", sha256=hashlib.sha256(content).hexdigest(), source_type="user", provenance="owner_declared", size_bytes=len(content), state="ready"))
            await session.commit()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        async with AsyncSessionLocal() as session:
            jobs = (await session.execute(__import__("sqlalchemy").select(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id == self.asset_id))).scalars().all()
            derivatives = [job.derivative_asset_id for job in jobs if job.derivative_asset_id]
            await session.execute(delete(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id == self.asset_id))
            if derivatives:
                await session.execute(delete(AssetRecord).where(AssetRecord.id.in_(derivatives)))
            await session.execute(delete(AssetRecord).where(AssetRecord.id == self.asset_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()

    async def test_capability_and_image_transform_api(self):
        capability = await self.client.get("/api/assets/transforms/capability")
        self.assertEqual(capability.status_code, 200)
        self.assertIn("available", capability.json())
        if not capability.json()["available"]:
            self.skipTest("FFmpeg unavailable")
        transformed = await self.client.post(f"/api/assets/{self.asset_id}/transform/image", json={"output_path": "variants/api.webp", "parameters": {"format": "webp", "width": 10, "height": 8}, "execution_id": f"api-media-{uuid.uuid4().hex[:8]}"})
        self.assertEqual(transformed.status_code, 200, transformed.text)
        self.assertEqual(transformed.json()["asset"]["width"], 10)
        self.assertEqual(transformed.json()["job"]["status"], "completed")

    async def test_unknown_transform_and_path_traversal_are_rejected(self):
        unknown = await self.client.post(f"/api/assets/{self.asset_id}/transform/unknown", json={"output_path": "variants/x.png", "parameters": {}})
        traversal = await self.client.post(f"/api/assets/{self.asset_id}/transform/image", json={"output_path": "../escape.webp", "parameters": {"format": "webp", "width": 10}})
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(traversal.status_code, 422)


if __name__ == "__main__":
    unittest.main()
