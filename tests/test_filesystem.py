import os
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.filesystem import PathPolicy, PathPolicyError
from core.ai_fleet.engine.skill_adapter import SkillAdapter
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import DelegateSkillRecord


class PathPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PathPolicy()

    def test_absolute_existing_directory_and_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "file.txt"
            file.write_text("safe")
            self.assertEqual(self.policy.existing_directory(root), root.resolve())
            self.assertEqual(self.policy.existing_file(file), file.resolve())
            self.assertEqual(self.policy.contained_file(root, file), file.resolve())

    def test_relative_control_and_missing_paths_are_rejected(self):
        for value in ["relative/path", "bad\x00path", "bad\npath", str(Path(tempfile.gettempdir()) / "missing-ai-fleet-file")]:
            with self.assertRaises(PathPolicyError, msg=value):
                self.policy.existing_file(value)

    def test_parent_traversal_outside_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("outside")
            with self.assertRaises(PathPolicyError):
                self.policy.contained_file(root, root / ".." / "outside.txt")

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink support required")
    def test_symlink_escape_is_rejected_where_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("outside")
            link = root / "link.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks require privileges on this Windows host")
            with self.assertRaises(PathPolicyError):
                self.policy.contained_file(root, link)


class SkillWorkspaceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.skill_id = f"outside-skill-{id(self)}"

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            record = await session.get(DelegateSkillRecord, self.skill_id)
            if record:
                await session.delete(record)
                await session.commit()

    async def test_script_outside_workspace_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            workspace = base / "workspace"
            workspace.mkdir()
            outside = base / "outside.py"
            outside.write_text("raise SystemExit('must not execute')")
            async with AsyncSessionLocal() as session:
                session.add(DelegateSkillRecord(id=self.skill_id, name="Outside", adapter_type="python", script_path=str(outside)))
                await session.commit()
            with self.assertRaises(PathPolicyError):
                await SkillAdapter().run_skill(self.skill_id, "input", workspace=str(workspace), permission_profile="developer")

    async def test_safe_workspace_blocks_inside_script(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            script = workspace / "inside.py"
            script.write_text("print('must not execute')")
            async with AsyncSessionLocal() as session:
                record = await session.get(DelegateSkillRecord, self.skill_id)
                if record:
                    record.script_path = str(script)
                    record.adapter_type = "python"
                else:
                    session.add(DelegateSkillRecord(id=self.skill_id, name="Inside", adapter_type="python", script_path=str(script)))
                await session.commit()
            with self.assertRaises(PermissionError):
                await SkillAdapter().run_skill(self.skill_id, "input", workspace=str(workspace), permission_profile="safe")


if __name__ == "__main__":
    unittest.main()
