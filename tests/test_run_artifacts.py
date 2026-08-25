import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.services.run_artifacts import RunArtifactService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import RunArtifactRecord, RunAttemptRecord, TaskRun, WorkspaceRecord


class RunArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.workspace_id = f"artifact-workspace-{id(self)}"
        self.run_id = f"artifact-run-{id(self)}"
        self.attempt_id = f"artifact-attempt-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Artifacts", path=str(self.root.resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(TaskRun(id=self.run_id, prompt="artifact", workspace_id=self.workspace_id, status="completed"))
            session.add(RunAttemptRecord(id=self.attempt_id, run_id=self.run_id, attempt_number=1, executor_type="cli", status="completed"))
            await session.commit()
        self.service = RunArtifactService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunArtifactRecord).where(RunArtifactRecord.run_id == self.run_id))
            attempt = await session.get(RunAttemptRecord, self.attempt_id)
            if attempt: await session.delete(attempt)
            run = await session.get(TaskRun, self.run_id)
            if run: await session.delete(run)
            workspace = await session.get(WorkspaceRecord, self.workspace_id)
            if workspace: await session.delete(workspace)
            await session.commit()
        self.folder.cleanup()

    async def test_registers_relative_hashed_artifact(self):
        target = self.root / "dist" / "report.txt"
        target.parent.mkdir()
        target.write_text("artifact content")
        async with AsyncSessionLocal() as session:
            record = await self.service.register(session, self.run_id, "dist/report.txt", "report", self.attempt_id, {"label": "Report", "nested": {"ignored": True}})
        self.assertEqual(record.path, "dist/report.txt")
        self.assertEqual(len(record.sha256), 64)
        payload = record.to_dict()
        self.assertEqual(payload["metadata"]["label"], "Report")
        self.assertNotIn("nested", payload["metadata"])
        self.assertEqual(payload["metadata"]["mime_type"], "text/plain")

    async def test_outside_and_wrong_attempt_are_rejected(self):
        outside = self.root.parent / f"outside-{id(self)}.txt"
        outside.write_text("outside")
        inside = self.root / "inside.txt"
        inside.write_text("inside")
        try:
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception):
                    await self.service.register(session, self.run_id, str(outside), "created")
                with self.assertRaises(Exception):
                    await self.service.register(session, self.run_id, "inside.txt", "created", "other-attempt")
        finally:
            outside.unlink(missing_ok=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink support required")
    async def test_symlink_escape_is_rejected(self):
        outside = self.root.parent / f"outside-link-{id(self)}.txt"
        outside.write_text("outside")
        link = self.root / "link.txt"
        try:
            try: link.symlink_to(outside)
            except OSError: self.skipTest("Symlink privilege unavailable")
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception):
                    await self.service.register(session, self.run_id, "link.txt", "created")
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
