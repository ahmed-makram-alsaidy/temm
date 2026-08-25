import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, RunAttemptRecord, TaskRun, WorkspaceRecord


class RunApiLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.workspace_id = f"run-workspace-{id(self)}"
        self.agent_id = f"run-agent-{id(self)}"
        self.run_id = f"run-api-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Run Workspace", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]', is_default=True))
            session.add(AgentRecord(id=self.agent_id, name="Run Agent", cli_command="python", detected_path="python", discovery_source="manual", discovery_state="verified", status="ready", auth_state="not_required", tool_kind="agent", capabilities='["coding"]', invocation_args='["-c", "print(123)"]', user_enabled=True, lifecycle_status="active", permission_profile="developer"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_id))
            run = await session.get(TaskRun, self.run_id)
            if run: await session.delete(run)
            agent = await session.get(AgentRecord, self.agent_id)
            if agent: await session.delete(agent)
            workspace = await session.get(WorkspaceRecord, self.workspace_id)
            if workspace: await session.delete(workspace)
            await session.commit()
        self.folder.cleanup()

    async def test_preflight_uses_canonical_executable_route_decision(self):
        scan = {"configured_providers": {}, "discovered_tools": [], "ollama_status": {"running": False, "models": []}}
        with patch("core.ai_fleet.engine.execution_readiness.system_scanner.scan_system", return_value=scan):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.post("/api/tasks/preflight", json={"prompt": "def fibonacci(n): fix this python function", "agent_id": self.agent_id, "workspace_id": self.workspace_id})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["can_execute"], payload)
        self.assertEqual(payload["route_decision"]["decision_basis"], "preflight_executable_routes_only")
        self.assertEqual(payload["route_decision"]["selected_route"]["agent_id"], self.agent_id)
        self.assertEqual(payload["route_explanation"]["selected_route_id"], f"agent:{self.agent_id}")
        self.assertTrue(any(item["dimension"] == "cost" for item in payload["route_explanation"]["unknowns"]))

    async def test_real_route_uses_canonical_run_and_attempt(self):
        preflight = {
            "can_execute": True, "execution_method": "cli",
            "recommendation": {"selected_model": {"id": "gpt-4o"}, "explanation": "test", "fallback_chain": [], "task_analysis": {"category": "coding"}},
            "selected_model": None,
            "selected_agent": {"id": self.agent_id},
            "selected_workspace": {"id": self.workspace_id},
        }
        with patch("core.ai_fleet.api.routes.build_execution_preflight", return_value=preflight):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.post("/api/tasks/run", json={"task_id": self.run_id, "prompt": "test", "agent_id": self.agent_id, "workspace_id": self.workspace_id})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIsNotNone(payload["started_at"])
        self.assertIsNotNone(payload["completed_at"])
        self.assertIsNone(payload["actual_cost"])
        self.assertEqual(payload["cost_provenance"], "unknown")
        self.assertEqual(payload["financials"]["value"]["category"], "estimated_avoided_cost")
        self.assertIsNone(payload["financials"]["value"]["amount"])
        async with AsyncSessionLocal() as session:
            attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_id))).scalars().all()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, "completed")
        self.assertEqual(attempts[0].to_dict()["receipt"]["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
