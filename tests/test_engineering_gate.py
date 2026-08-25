import json
import os
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.services.engineering_gate import EngineeringGateService


class FakeManager:
    def __init__(self): self.calls = []
    async def execute_argv(self, argv, task_id, cwd=None, timeout_seconds=0):
        self.calls.append({"argv": argv, "cwd": cwd})
        return {"success": True, "outcome": "completed", "state": "completed", "exit_code": 0, "error_code": None, "duration_ms": 1, "stdout": "ok", "stderr": "", "task_id": task_id}


class EngineeringGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovers_only_configured_scripts_and_records_exact_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "lint": "eslint .", "build": "vite build", "other": "x"}}), encoding="utf-8")
            checks = EngineeringGateService().discover(root)
            manager = FakeManager()
            results = await EngineeringGateService().run(manager, root, checks)
        self.assertEqual([item["kind"] for item in checks], ["test", "lint", "build"])
        self.assertEqual(manager.calls[0]["argv"], ["npm.cmd" if os.name == "nt" else "npm", "run", "test"])
        self.assertTrue(all(item["status"] == "passed" for item in results))
        self.assertEqual(results[0]["receipt"]["exit_code"], 0)

    async def test_empty_and_pyproject_fixtures_do_not_assume_framework(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(EngineeringGateService().discover(root), [])
            (root / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
            checks = EngineeringGateService().discover(root)
            results = await EngineeringGateService().run(FakeManager(), root, checks)
        self.assertIsNone(checks[0]["argv"])
        self.assertEqual(results[0]["status"], "not_run")
        self.assertIn("without repository instructions", results[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
