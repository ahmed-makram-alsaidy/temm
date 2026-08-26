"""Durable local tool-execution contract tests added by the v0.1.1 hotfix.

Covers the full chain that v0.1.0 left unproven: structured argv execution of
real installed tools, failure truth (non-zero exit, missing executable,
timeout), Windows paths containing spaces, the advertised-capability versus
runtime-handler registry contract, the OpenCode-only project-dispatch
fallback, and a product-path run through the public REST surface.
"""

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
import psutil
from sqlalchemy import delete

from core.ai_fleet.cli_invocation import build_cli_args
from core.ai_fleet.discovery import DiscoveryManifestLoader
from core.ai_fleet.engine.execution_readiness import build_execution_preflight
from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.main import app
from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService
from core.ai_fleet.storage.database import AsyncSessionLocal, engine, init_db
from core.ai_fleet.storage.models import (
    AgentRecord,
    AssetCollectionMemberRecord,
    OrchestrationTaskRecord,
    ProjectRecord,
    RunAttemptRecord,
    TaskRun,
    WorkspaceRecord,
)

STUB_CMD = """@echo off
if /i "%~1"=="--version" (
  echo stub-1.0
  exit /b 0
)
echo {marker}
exit /b {exit_code}
"""


def _write_stub(directory: Path, name: str, marker: str, exit_code: int = 0) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(STUB_CMD.format(marker=marker, exit_code=exit_code), encoding="ascii")
    return str(path)


def _agent(**overrides):
    values = {
        "id": f"agent-{uuid.uuid4().hex[:10]}",
        "name": "Contract Stub",
        "cli_command": "stubtool.cmd",
        "tool_kind": "agent",
        "user_enabled": True,
        "lifecycle_status": "active",
        "discovery_state": "verified",
        "status": "ready",
        "auth_state": "not_required",
        "input_method": "argument",
        "output_method": "stdout",
        "invocation_args": json.dumps(["{prompt}"]),
        "capabilities": json.dumps(["coding", "general"]),
        "working_directory": "workspace",
        "is_installed": True,
        "detected_path": "C:\\fake dir\\stubtool.cmd",
        "permission_profile": "developer",
    }
    values.update(overrides)
    return AgentRecord(**values)


class ToolExecutionProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.manager.shutdown()
        await engine.dispose()

    async def test_python_stdout_exit_zero_is_recorded(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        receipt = await self.manager.execute_argv(
            ["python", "-c", "print('TEMM_EXEC_OK')"],
            task_id=f"exec-python-{uuid.uuid4().hex[:8]}",
            timeout_seconds=30,
        )
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("TEMM_EXEC_OK", receipt["stdout"])

    async def test_git_version_probe_captures_output(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        receipt = await self.manager.execute_argv(["git", "--version"], task_id=f"exec-git-{uuid.uuid4().hex[:8]}", timeout_seconds=30)
        self.assertTrue(receipt["success"], receipt)
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("git version", receipt["stdout"])

    async def test_node_evaluates_marker_when_installed(self):
        if not shutil_which("node"):
            self.skipTest("node is not installed")
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        receipt = await self.manager.execute_argv(["node", "-e", "console.log('TEMM_NODE_OK')"], task_id=f"exec-node-{uuid.uuid4().hex[:8]}", timeout_seconds=30)
        self.assertTrue(receipt["success"], receipt)
        self.assertIn("TEMM_NODE_OK", receipt["stdout"])

    async def test_non_zero_exit_is_failure_not_success(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        receipt = await self.manager.execute_argv(["python", "-c", "import sys; sys.exit(7)"], task_id=f"exec-exit7-{uuid.uuid4().hex[:8]}", timeout_seconds=30)
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["exit_code"], 7)
        self.assertEqual(receipt["outcome"], "non_zero_exit")

    async def test_missing_executable_returns_actionable_receipt(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / f"missing-tool-{uuid.uuid4().hex[:6]}.exe")
            receipt = await self.manager.execute_argv([missing], task_id=f"exec-missing-{uuid.uuid4().hex[:8]}", timeout_seconds=15)
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["outcome"], "launch_failed")
        self.assertEqual(receipt["error_code"], "executable_not_found")

    async def test_timeout_kills_process_tree(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        receipt = await self.manager.execute_argv(
            ["python", "-c", "import time; print('started', flush=True); time.sleep(20)"],
            task_id=f"exec-timeout-{uuid.uuid4().hex[:8]}",
            timeout_seconds=2,
        )
        self.assertTrue(receipt["timed_out"])
        self.assertFalse(receipt["success"])
        pid = receipt["pid"]
        for _ in range(100):
            if not psutil.pid_exists(pid):
                break
            await __import__("asyncio").sleep(0.05)
        self.assertFalse(psutil.pid_exists(pid))

    @unittest.skipUnless(sys.platform == "win32", "executes a .cmd stub through cmd.exe")
    async def test_path_with_spaces_executes_without_quoting_defect(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.5)
        with tempfile.TemporaryDirectory() as directory:
            spaced = Path(directory) / f"te mm space {uuid.uuid4().hex[:6]}"
            stub = _write_stub(spaced, "spacey tool.cmd", "TEMM_SPACES_OK")
            receipt = await self.manager.execute_argv([stub], task_id=f"exec-spaces-{uuid.uuid4().hex[:8]}", timeout_seconds=30)
        self.assertTrue(receipt["success"], receipt)
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("TEMM_SPACES_OK", receipt["stdout"])


class RegistryConsistencyTests(unittest.TestCase):
    """Every advertised executable agent capability must map to a real handler."""

    def test_every_manifest_agent_has_an_executable_invocation_contract(self):
        for adapter in DiscoveryManifestLoader().load():
            if adapter.kind.value != "agent":
                continue
            with self.subTest(adapter=adapter.adapter_id):
                self.assertTrue(adapter.executable_names)
                self.assertIn(adapter.input_method, {"argument", "stdin"})
                self.assertIn(adapter.output_method, {"stdout", "json"})
                self.assertTrue(adapter.invocation_args, "agent must declare invocation args")
                record = _agent(
                    id=adapter.adapter_id,
                    cli_command=adapter.executable_names[0],
                    input_method=adapter.input_method,
                    output_method=adapter.output_method,
                    invocation_args=json.dumps(list(adapter.invocation_args)),
                    capabilities=json.dumps(list(adapter.capabilities)),
                )
                argv = build_cli_args(record, "PROBE PROMPT", "WORKSPACE")
                self.assertEqual(argv[0], record.detected_path)
                self.assertNotIn("{prompt}", argv)

    def test_execution_ready_reflects_auth_truth(self):
        ready = _agent()
        self.assertTrue(ready.to_dict()["execution_ready"])
        blocked = _agent(id="blocked-agent", auth_state="unknown")
        self.assertFalse(blocked.to_dict()["execution_ready"])
        failed = _agent(id="failed-agent", auth_state="failed")
        self.assertFalse(failed.to_dict()["execution_ready"])
        disabled = _agent(id="disabled-agent", user_enabled=False)
        self.assertFalse(disabled.to_dict()["execution_ready"])


class OpencodeOnlyDispatchFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Regression: an OpenCode-only machine must dispatch through its verified agent."""

    async def asyncSetUp(self):
        await init_db()
        self.ids = {}

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.like("fallback-%")))
            await session.execute(delete(TaskRun).where(TaskRun.id.like("fallback-%")))
            if self.ids.get("task"):
                await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id == self.ids["task"]))
            if self.ids.get("agent"):
                await session.execute(delete(AgentRecord).where(AgentRecord.id == self.ids["agent"]))
            if self.ids.get("project"):
                await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.ids["project"]))
            if self.ids.get("workspace"):
                await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.ids["workspace"]))
            await session.commit()
        await engine.dispose()

    async def test_verified_opencode_agent_satisfies_dispatch_without_model_routes(self):
        suffix = uuid.uuid4().hex[:8]
        project_id = f"fallback-project-{suffix}"
        workspace_id = f"fallback-workspace-{suffix}"
        agent_id = f"fallback-opencode-{suffix}"
        task_id = f"fallback-task-{suffix}"
        self.ids = {"project": project_id, "workspace": workspace_id, "agent": agent_id, "task": task_id}
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=project_id, name="Fallback", slug=f"fallback-{suffix}", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=workspace_id, name="Fallback WS", path="D:/nonexistent-fallback", permission_profile="developer", allowed_shells="[]"))
            session.add(_agent(
                id=agent_id,
                name="OpenCode",
                cli_command="opencode",
                detected_path="C:\\fake npm dir\\opencode.cmd",
                capabilities=json.dumps(["coding", "general"]),
                invocation_args=json.dumps(["run", "{prompt}", "--format", "json"]),
            ))
            session.add(OrchestrationTaskRecord(id=task_id, project_id=project_id, task_type="implementation", title="Implement helper", description="Create helper module", state="planned", executor_needs_json=json.dumps({"capabilities": ["coding"]})))
            await session.commit()
            task = await session.get(OrchestrationTaskRecord, task_id)
            agent = await session.get(AgentRecord, agent_id)
            decision = await ProjectDispatcherService(None)._select_model(session, task, agent)
        self.assertEqual(decision["selection_basis"], "verified_capability_agent")
        self.assertEqual(decision["provider"], agent_id)
        self.assertIsNone(decision["model_id"])


class ProductToolRunApiTests(unittest.IsolatedAsyncioTestCase):
    """Product-path proof: onboarded tool -> preflight -> real run -> recorded receipt."""

    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "ws").mkdir()
        self.spaced = self.root / "tool dir with spaces"
        self.stub = _write_stub(self.spaced, "proof tool.cmd", "TEMM_PRODUCT_OK")
        self.transport = httpx.ASGITransport(app=app)
        self.agent_ids = []
        self.workspace_ids = []
        self.run_ids = []

    async def asyncTearDown(self):
        try:
            async with AsyncSessionLocal() as session:
                if self.run_ids:
                    await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(self.run_ids)))
                    await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
                if self.agent_ids:
                    await session.execute(delete(AgentRecord).where(AgentRecord.id.in_(self.agent_ids)))
                if self.workspace_ids:
                    await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id.in_(self.workspace_ids)))
                await session.commit()
        finally:
            self.folder.cleanup()
            await engine.dispose()

    def _client(self):
        return httpx.AsyncClient(transport=self.transport, base_url="http://test")

    @unittest.skipUnless(sys.platform == "win32", "spawns a .cmd stub via cmd.exe")
    async def test_onboarded_tool_executes_through_product_run_api(self):
        async with self._client() as client:
            created = (await client.post("/api/agents", json={
                "name": "Proof Stub",
                "executable": self.stub,
                "version_probe_args": ["--version"],
                "invocation_args": ["{prompt}"],
                "capabilities": ["coding", "general"],
                "auth_required": False,
                "probe_timeout_seconds": 8,
            })).json()
            self.assertEqual(created["discovery_state"], "verified", created)
            self.assertEqual(created["auth_state"], "not_required")
            self.assertTrue(created["execution_ready"])
            self.agent_ids.append(created["id"])

            workspace = (await client.post("/api/workspaces", json={
                "name": "Product Proof",
                "path": str(self.root / "ws"),
                "permission_profile": "developer",
            })).json()
            self.workspace_ids.append(workspace["id"])

            preflight = (await client.post("/api/tasks/preflight", json={
                "prompt": "Run the proof stub.",
                "workspace_id": workspace["id"],
            })).json()
            self.assertTrue(preflight["can_execute"], preflight)
            self.assertEqual(preflight["execution_method"], "cli")
            self.assertEqual(preflight["selected_agent"]["id"], created["id"])

            run = (await client.post("/api/tasks/run", json={
                "prompt": "Print the product proof marker and finish.",
                "agent_id": created["id"],
                "workspace_id": workspace["id"],
            })).json()
            self.run_ids.append(run["id"])
            self.assertEqual(run["status"], "completed", run)
            self.assertEqual(run["selected_agent_id"], created["id"])

            attempts = (await client.get(f"/api/runs/{run['id']}/attempts")).json()
            self.assertEqual(attempts[0]["status"], "completed")
            self.assertEqual(attempts[0]["receipt"]["exit_code"], 0)
            self.assertIn("TEMM_PRODUCT_OK", attempts[0]["receipt"]["stdout"])
            output = (await client.get(f"/api/runs/{run['id']}/output")).json()
            self.assertTrue(any("TEMM_PRODUCT_OK" in item["content"] for item in output))

    @unittest.skipUnless(sys.platform == "win32", "spawns a .cmd stub via cmd.exe for auth gating")
    async def test_unauthenticated_discovered_tool_blocks_with_actionable_reason(self):
        gated_stub = _write_stub(self.spaced / "gated", f"gated tool {uuid.uuid4().hex[:6]}.cmd", "TEMM_GATED_OK")
        async with self._client() as client:
            gated = (await client.post("/api/agents", json={
                "name": "Gated Stub",
                "executable": gated_stub,
                "version_probe_args": ["--version"],
                "invocation_args": ["{prompt}"],
                "capabilities": ["coding", "general"],
                "auth_required": True,
                "auth_method": "account_or_api_key",
                "probe_timeout_seconds": 8,
            })).json()
            self.agent_ids.append(gated["id"])
            self.assertEqual(gated["discovery_state"], "verified")
            self.assertEqual(gated["auth_state"], "unknown")
            self.assertFalse(gated["execution_ready"])

            preflight = (await client.post("/api/tasks/preflight", json={
                "prompt": "Run the gated stub.",
                "agent_id": gated["id"],
            })).json()
            self.assertFalse(preflight["can_execute"])
            codes = {blocker["code"] for blocker in preflight["blockers"]}
            self.assertIn("agent_auth_unverified", codes)


def shutil_which(name):
    import shutil

    return shutil.which(name)


class CapabilityRoutingTests(unittest.IsolatedAsyncioTestCase):
    """Multiple discovered tools must route by capability, not by discovery order."""

    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        suffix = uuid.uuid4().hex[:8]
        self.workspace_id = f"routing-workspace-{suffix}"
        # Named so the coding tool sorts first alphabetically: a capability match
        # must beat ordering, otherwise "the first discovered tool" wins every task.
        self.coding_id = f"aaa-coding-{suffix}"
        self.research_id = f"zzz-research-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Routing WS", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]', is_default=True))
            session.add(_agent(id=self.coding_id, name="AAA Coding Stub", discovery_source="manual", capabilities=json.dumps(["coding"])))
            session.add(_agent(id=self.research_id, name="ZZZ Research Stub", discovery_source="manual", capabilities=json.dumps(["research"])))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AgentRecord).where(AgentRecord.id.in_([self.coding_id, self.research_id])))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()
        await engine.dispose()

    async def _preflight(self, required):
        scan = {"configured_providers": {}, "discovered_tools": [], "ollama_status": {"running": False, "models": []}}
        with patch("core.ai_fleet.engine.execution_readiness.system_scanner.scan_system", return_value=scan):
            return await build_execution_preflight(
                prompt="Do the contracted work in this workspace.",
                workspace_id=self.workspace_id,
                required_capabilities=required,
            )

    async def test_research_contract_selects_the_research_tool(self):
        preflight = await self._preflight(["research"])
        self.assertTrue(preflight["can_execute"], preflight["blockers"])
        self.assertEqual(preflight["execution_method"], "cli")
        self.assertEqual(preflight["selected_agent"]["id"], self.research_id)

    async def test_coding_contract_selects_the_coding_tool(self):
        preflight = await self._preflight(["coding"])
        self.assertTrue(preflight["can_execute"], preflight["blockers"])
        self.assertEqual(preflight["selected_agent"]["id"], self.coding_id)


if __name__ == "__main__":
    unittest.main()
