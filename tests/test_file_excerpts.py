import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.services.file_excerpts import FileExcerptService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import WorkspaceRecord


class FileExcerptSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.folder = tempfile.TemporaryDirectory(); self.root = Path(self.folder.name); self.workspace_id = f"excerpt-{id(self)}"
        async with AsyncSessionLocal() as session: session.add(WorkspaceRecord(id=self.workspace_id, name="Excerpt", path=str(self.root.resolve()), permission_profile="safe", allowed_shells='[]')); await session.commit()
        self.service = FileExcerptService()
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session: await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id)); await session.commit()
        self.folder.cleanup()

    async def test_bounded_text_redacts_secret_patterns_and_hashes(self):
        (self.root / "text.txt").write_text("line1\nsk-testsecret1234567890\nline3\nline4", encoding="utf-8")
        async with AsyncSessionLocal() as session: result = await self.service.extract(session, self.workspace_id, "text.txt", 2, 2, 100)
        self.assertNotIn("sk-testsecret", result["content"]); self.assertIn("[REDACTED]", result["content"]); self.assertTrue(result["redacted"]); self.assertEqual(result["start_line"], 2); self.assertTrue(result["truncated_lines"]); self.assertEqual(len(result["sha256"]), 64)

    async def test_binary_traversal_and_symlink_escape_are_rejected(self):
        (self.root / "binary.bin").write_bytes(b"abc\x00def")
        outside = self.root.parent / f"outside-{id(self)}.txt"; outside.write_text("outside")
        try:
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception): await self.service.extract(session, self.workspace_id, "binary.bin")
                with self.assertRaises(Exception): await self.service.extract(session, self.workspace_id, str(outside))
                if hasattr(os, "symlink"):
                    link = self.root / "link.txt"
                    try: link.symlink_to(outside)
                    except OSError: return
                    with self.assertRaises(Exception): await self.service.extract(session, self.workspace_id, "link.txt")
        finally: outside.unlink(missing_ok=True)

    async def test_utf16_is_supported_and_byte_limit_is_explicit(self):
        (self.root / "utf16.txt").write_text("alpha\nbeta", encoding="utf-16")
        async with AsyncSessionLocal() as session: result = await self.service.extract(session, self.workspace_id, "utf16.txt", max_bytes=3)
        self.assertEqual(result["encoding"], "utf-16"); self.assertTrue(result["truncated_bytes"]); self.assertEqual(result["content"], "alp")


if __name__ == "__main__": unittest.main()
