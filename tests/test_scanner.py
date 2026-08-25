import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import psutil
from sqlalchemy import delete

from core.ai_fleet.discovery import DiscoveryAdapter, DiscoveryManifestLoader, DiscoveryState, ToolKind
from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.engine.scanner import ExecutableResolver, SystemScanner
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord
from core.ai_fleet.storage.secret_vault import secret_vault
from core.ai_fleet.services.agent_lifecycle import AgentLifecycleError, AgentLifecycleService


class FakeManager:
    def __init__(self, receipts):
        self.receipts = list(receipts)
        self.calls = []

    async def execute_argv(self, args, task_id, timeout_seconds):
        self.calls.append((args, task_id, timeout_seconds))
        return self.receipts.pop(0)


class StaticResolver:
    def __init__(self, result):
        self.result = result

    def resolve(self, adapter):
        return self.result

    def resolve_manual(self, executable):
        return self.result


class SequenceResolver:
    def __init__(self, results):
        self.results = iter(results)

    def resolve(self, adapter):
        return next(self.results)


def adapter(**overrides):
    values = {
        "adapter_id": "test-agent",
        "display_name": "Test Agent",
        "kind": ToolKind.AGENT,
        "executable_names": ["test-agent"],
        "version_args": ["--version"],
        "version_pattern": r"^Test Agent \d+\.\d+$",
        "capabilities": ["streaming"],
        "common_locations": [],
        "invocation_args": ["{prompt}"],
        "input_method": "argument",
        "output_method": "stdout",
        "working_directory": "workspace",
        "timeout_seconds": 2.0,
        "health_args": [],
        "auth_required": False,
        "auth_method": "none",
        "auth_setup_instructions": "",
        "auth_probe_args": [],
        "auth_probe_parser": {},
        "source": "test",
    }
    values.update(overrides)
    return DiscoveryAdapter(**values)


def receipt(success=True, stdout="Test Agent 1.2", outcome="completed", error_code=None, exit_code=0):
    return {
        "success": success,
        "stdout": stdout,
        "stderr": "",
        "outcome": outcome,
        "error_code": error_code,
        "exit_code": exit_code,
        "duration_ms": 12,
    }


class ManifestContractTests(unittest.TestCase):
    def test_duplicate_adapter_ids_are_rejected(self):
        manifest = {
            "id": "duplicate-agent",
            "name": "Duplicate",
            "kind": "agent",
            "executables": ["duplicate"],
            "version_probe": {"args": ["--version"]},
            "capabilities": [],
            "execution": {"args": ["{prompt}"]},
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "one.json").write_text(json.dumps(manifest))
            (path / "two.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                DiscoveryManifestLoader([path]).load()

    def test_unknown_capability_is_rejected(self):
        manifest = {
            "id": "invalid-agent",
            "name": "Invalid",
            "kind": "agent",
            "executables": ["invalid"],
            "version_probe": {"args": []},
            "capabilities": ["imaginary_power"],
            "execution": {"args": []},
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "invalid.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                DiscoveryManifestLoader([path]).load()


class AuthProbeTests(unittest.IsolatedAsyncioTestCase):
    def record(self, parser, args=None):
        return AgentRecord(
            id="auth-probe-test",
            name="Auth Probe",
            cli_command="C:\\agent.exe",
            detected_path="C:\\agent.exe",
            auth_state="unknown",
            auth_method="account",
            auth_probe_args=json.dumps(args or ["auth", "status"]),
            auth_probe_parser=json.dumps(parser),
            probe_timeout_seconds=2,
        )

    async def test_json_auth_probe_verifies_only_matching_field(self):
        manager = FakeManager([receipt(stdout='{"loggedIn": true}')])
        scanner = SystemScanner(adapters=[], manager=manager)
        result = await scanner.probe_auth(self.record({"type": "json_field", "path": "loggedIn", "equals": True}))

        self.assertEqual(result["state"], "verified")
        self.assertTrue(result["evidence"]["verified"])

    async def test_malformed_or_mismatched_auth_output_fails(self):
        manager = FakeManager([receipt(stdout="not-json"), receipt(stdout="signed out")])
        scanner = SystemScanner(adapters=[], manager=manager)
        malformed = await scanner.probe_auth(self.record({"type": "json_field", "path": "loggedIn", "equals": True}))
        mismatch = await scanner.probe_auth(self.record({"type": "output_regex", "pattern": "(?i)logged in"}))

        self.assertEqual(malformed["state"], "failed")
        self.assertEqual(mismatch["state"], "failed")

    async def test_missing_auth_probe_remains_unknown(self):
        scanner = SystemScanner(adapters=[], manager=FakeManager([]))
        result = await scanner.probe_auth(self.record({}, args=[]))
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["evidence"]["reason"], "auth_probe_not_configured")

    async def test_auth_probe_timeout_is_failed_and_process_cleaned(self):
        manager = ProcessManager(graceful_shutdown_seconds=0.1)
        scanner = SystemScanner(adapters=[], manager=manager)
        record = AgentRecord(
            id="auth-timeout",
            name="Auth Timeout",
            cli_command=sys.executable,
            detected_path=sys.executable,
            auth_state="unknown",
            auth_method="account",
            auth_probe_args=json.dumps(["-c", "import time;time.sleep(30)"]),
            auth_probe_parser=json.dumps({"type": "exit_zero"}),
            probe_timeout_seconds=0.1,
        )
        result = await scanner.probe_auth(record)
        receipt_value = next(reversed(manager._receipts.values()))

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["evidence"]["outcome"], "timed_out")
        self.assertFalse(psutil.pid_exists(receipt_value["pid"]))
        await manager.shutdown()


class ScannerContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_executable_found_and_version_verified(self):
        manager = FakeManager([receipt()])
        scanner = SystemScanner(
            adapters=[adapter()],
            resolver=StaticResolver({"path": "C:\\Tools With Space\\agent.exe", "source": "path", "shim": False}),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)

        tool = result["discovered_tools"][0]
        self.assertEqual(tool["state"], DiscoveryState.VERIFIED.value)
        self.assertEqual(tool["path"], "C:\\Tools With Space\\agent.exe")
        self.assertEqual(manager.calls[0][0], ["C:\\Tools With Space\\agent.exe", "--version"])
        self.assertEqual(manager.calls[0][2], 2.0)

    async def test_executable_missing_is_unavailable_without_probe(self):
        manager = FakeManager([])
        scanner = SystemScanner(adapters=[adapter()], resolver=StaticResolver(None), manager=manager)
        result = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual(result["discovered_tools"][0]["state"], DiscoveryState.UNAVAILABLE.value)
        self.assertEqual(manager.calls, [])

    async def test_non_zero_and_timeout_probes_are_broken(self):
        manager = FakeManager([
            receipt(False, outcome="non_zero_exit", error_code="non_zero_exit", exit_code=2),
            receipt(False, outcome="timed_out", error_code="execution_timeout", exit_code=1),
        ])
        scanner = SystemScanner(
            adapters=[adapter(adapter_id="one"), adapter(adapter_id="two")],
            resolver=SequenceResolver([
                {"path": "C:\\one.exe", "source": "path", "shim": False},
                {"path": "C:\\two.exe", "source": "path", "shim": False},
            ]),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual([item["state"] for item in result["discovered_tools"]], ["broken", "broken"])
        self.assertEqual(result["discovered_tools"][0]["evidence"]["reason"], "non_zero_exit")
        self.assertEqual(result["discovered_tools"][1]["evidence"]["reason"], "execution_timeout")

    async def test_malformed_and_empty_output_are_unverified(self):
        manager = FakeManager([receipt(stdout="unexpected words"), receipt(stdout="")])
        scanner = SystemScanner(
            adapters=[adapter(adapter_id="one"), adapter(adapter_id="two")],
            resolver=StaticResolver({"path": "C:\\agent.exe", "source": "path", "shim": False}),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual([item["state"] for item in result["discovered_tools"]], ["unverified", "unverified"])

    async def test_no_version_probe_is_detected_with_truthful_defaults(self):
        scanner = SystemScanner(
            adapters=[adapter(version_args=[], version_pattern=None, capabilities=[])],
            resolver=StaticResolver({"path": "C:\\agent.exe", "source": "path", "shim": False}),
            manager=FakeManager([]),
        )
        result = await scanner.scan_system(persist=False, check_services=False)
        tool = result["discovered_tools"][0]

        self.assertEqual(tool["state"], "detected")
        self.assertEqual(tool["capabilities"], [])
        self.assertFalse(tool["supports_pty"])
        self.assertFalse(tool["supports_interactive"])

    async def test_duplicate_path_is_not_counted_as_two_verified_tools(self):
        manager = FakeManager([receipt(), receipt()])
        scanner = SystemScanner(
            adapters=[adapter(adapter_id="one"), adapter(adapter_id="two")],
            resolver=StaticResolver({"path": "C:\\same.exe", "source": "path", "shim": False}),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual(result["discovered_tools"][0]["state"], "verified")
        self.assertEqual(result["discovered_tools"][1]["state"], "unverified")
        self.assertEqual(result["discovered_tools"][1]["evidence"]["reason"], "duplicate_executable_path")

    async def test_rescan_reflects_current_probe_evidence(self):
        manager = FakeManager([receipt(), receipt(False, outcome="timed_out", error_code="execution_timeout")])
        scanner = SystemScanner(
            adapters=[adapter()],
            resolver=StaticResolver({"path": "C:\\agent.exe", "source": "path", "shim": False}),
            manager=manager,
        )
        first = await scanner.scan_system(persist=False, check_services=False)
        second = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual(first["discovered_tools"][0]["state"], "verified")
        self.assertEqual(second["discovered_tools"][0]["state"], "broken")

    async def test_failed_health_probe_marks_verified_binary_broken(self):
        manager = FakeManager([
            receipt(),
            receipt(False, outcome="non_zero_exit", error_code="non_zero_exit", exit_code=3),
        ])
        scanner = SystemScanner(
            adapters=[adapter(health_args=["status"])],
            resolver=StaticResolver({"path": "C:\\agent.exe", "source": "path", "shim": False}),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)

        self.assertEqual(result["discovered_tools"][0]["state"], "broken")
        self.assertEqual(result["discovered_tools"][0]["evidence"]["reason"], "health_probe_failed")
        self.assertEqual(len(manager.calls), 2)

    async def test_real_probe_timeout_cleans_process(self):
        manager = ProcessManager(graceful_shutdown_seconds=0.1)
        scanner = SystemScanner(
            adapters=[adapter(version_args=["-c", "import time;time.sleep(30)"], version_pattern=None, timeout_seconds=0.1)],
            resolver=StaticResolver({"path": sys.executable, "source": "path", "shim": False}),
            manager=manager,
        )
        result = await scanner.scan_system(persist=False, check_services=False)
        receipts = list(manager._receipts.values())

        self.assertEqual(result["discovered_tools"][0]["state"], "broken")
        self.assertEqual(receipts[0]["outcome"], "timed_out")
        self.assertFalse(psutil.pid_exists(receipts[0]["pid"]))
        await manager.shutdown()


@unittest.skipUnless(sys.platform == "win32", "Windows shim resolution")
class WindowsResolverTests(unittest.TestCase):
    def test_cmd_shim_and_spaces_are_resolved(self):
        with tempfile.TemporaryDirectory(prefix="AI Fleet Space ") as folder:
            shim = Path(folder) / "future-ai.cmd"
            shim.write_text("@echo off\r\n")
            resolver = ExecutableResolver(which=lambda name: str(shim) if name == "future-ai" else None)
            result = resolver.resolve(adapter(executable_names=["future-ai"]))

        self.assertTrue(result["shim"])
        self.assertEqual(result["extension"], ".cmd")
        self.assertIn("AI Fleet Space", result["path"])

    def test_spaced_cmd_shim_executes_through_process_manager(self):
        with tempfile.TemporaryDirectory(prefix="AI Fleet Space ") as folder:
            shim = Path(folder) / "future-ai.cmd"
            shim.write_text("@echo off\r\necho Future AI 1.2\r\n")
            manager = ProcessManager()
            result = asyncio.run(manager.execute_argv([str(shim), "--version"], task_id="spaced-shim", timeout_seconds=3))

        self.assertTrue(result["success"])
        self.assertIn("Future AI 1.2", result["stdout"])

    def test_powershell_shim_executes_without_shell_string(self):
        with tempfile.TemporaryDirectory(prefix="AI Fleet PS Space ") as folder:
            shim = Path(folder) / "future-ai.ps1"
            shim.write_text("Write-Output 'Future PS 2.0'\n")
            manager = ProcessManager()
            result = asyncio.run(manager.execute_argv([str(shim), "--version"], task_id="ps-shim", timeout_seconds=3))

        self.assertTrue(result["success"])
        self.assertIn("Future PS 2.0", result["stdout"])


class AgentLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.service = AgentLifecycleService(SystemScanner(adapters=[]), secret_vault)
        self.ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(AgentRecord).where(AgentRecord.id.in_(self.ids)))
                await session.commit()

    async def test_service_rejects_managed_edit_with_domain_error(self):
        async with AsyncSessionLocal() as session:
            record = await session.get(AgentRecord, "claude-code")
            with self.assertRaises(AgentLifecycleError) as raised:
                await self.service.update(session, "claude-code", {"name": "Forbidden"}, record.revision)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "managed_agent")

    async def test_service_retires_referenced_agent(self):
        agent_id = f"service-retire-{id(self)}"
        run_id = f"service-run-{id(self)}"
        self.ids.append(agent_id)
        async with AsyncSessionLocal() as session:
            session.add(AgentRecord(id=agent_id, name="Service Agent", cli_command=sys.executable, discovery_source="manual"))
            from core.ai_fleet.storage.models import TaskRun

            session.add(TaskRun(id=run_id, prompt="service", selected_agent_id=agent_id, status="completed"))
            await session.commit()
            result = await self.service.remove(session, agent_id)
            record = await session.get(AgentRecord, agent_id)
            run = await session.get(TaskRun, run_id)
            self.assertTrue(result["retired"])
            self.assertEqual(record.lifecycle_status, "retired")
            self.assertEqual(run.selected_agent_id, agent_id)
            await session.delete(run)
            await session.commit()


class ManualAgentApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.created_ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.created_ids:
                await session.execute(delete(AgentRecord).where(AgentRecord.id.in_(self.created_ids)))
                await session.commit()

    async def test_manual_custom_cli_and_duplicate_and_invalid_executable(self):
        unique_path = f"C:\\manual-test-{id(self)}.exe"
        inspect_result = {
            "state": "verified",
            "path": unique_path,
            "version": "Manual test 1.0",
            "evidence": {"resolved_path": unique_path},
        }
        transport = httpx.ASGITransport(app=app)
        payload = {
            "name": "Manual Test CLI",
            "executable": sys.executable,
            "version_probe_args": ["--version"],
            "invocation_args": ["-c", "print({prompt})"],
            "capabilities": [],
            "environment_refs": ["TEST_API_KEY"],
        }
        with patch("core.ai_fleet.api.routes.system_scanner.inspect_manual", return_value=inspect_result):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/agents", json=payload)
                self.assertEqual(response.status_code, 200)
                created = response.json()
                self.created_ids.append(created["id"])
                self.assertEqual(created["discovery_source"], "manual")
                self.assertEqual(created["discovery_state"], "verified")
                self.assertEqual(created["capabilities"], [])
                self.assertEqual(created["environment_refs"], ["TEST_API_KEY"])
                self.assertNotIn("TEST_API_KEY", created["discovery_evidence"].values())
                duplicate = await client.post("/api/agents", json=payload)
                self.assertEqual(duplicate.status_code, 409)

        with patch("core.ai_fleet.api.routes.system_scanner.inspect_manual", return_value={"state": "unavailable"}):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                invalid = await client.post("/api/agents", json={**payload, "executable": "missing-tool"})
        self.assertEqual(invalid.status_code, 422)

    async def test_auth_state_is_derived_and_cannot_be_self_verified(self):
        unique_path = f"C:\\auth-test-{id(self)}.exe"
        inspection = {"state": "verified", "path": unique_path, "version": "Auth 1.0", "evidence": {"resolved_path": unique_path}}
        transport = httpx.ASGITransport(app=app)
        payload = {
            "name": "Auth Agent",
            "executable": unique_path,
            "version_probe_args": ["--version"],
            "auth_required": True,
            "auth_method": "account",
            "auth_setup_instructions": "Use the official login flow.",
        }
        with patch("core.ai_fleet.api.routes.system_scanner.inspect_manual", return_value=inspection):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/agents", json=payload)
                forged = await client.post("/api/agents", json={**payload, "auth_state": "verified"})
        self.assertEqual(response.status_code, 200)
        created = response.json()
        self.created_ids.append(created["id"])
        self.assertEqual(created["auth_state"], "unknown")
        self.assertEqual(created["auth_method"], "account")
        self.assertFalse(created["auth_evidence"]["verified"])
        self.assertNotIn("verified", json.dumps(created["auth_setup_action"]).lower())
        self.assertEqual(forged.status_code, 422)

    async def test_agent_secret_references_never_return_values(self):
        agent_id = f"agent-secret-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(AgentRecord(
                id=agent_id,
                name="Secret Agent",
                cli_command=sys.executable,
                detected_path=sys.executable,
                discovery_source="manual",
                discovery_state="verified",
                status="ready",
                auth_state="unknown",
                auth_method="api_key",
            ))
            await session.commit()
        self.created_ids.append(agent_id)
        secret = "super-secret-agent-value-928374"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            set_response = await client.put(f"/api/agents/{agent_id}/secrets", json={"reference": "AGENT_API_KEY", "value": secret})
            list_response = await client.get(f"/api/agents/{agent_id}/secrets")
            agent_response = await client.get("/api/agents")
            delete_response = await client.delete(f"/api/agents/{agent_id}/secrets/AGENT_API_KEY")
        self.assertEqual(set_response.status_code, 200)
        self.assertEqual(set_response.json()["auth_state"], "configured")
        self.assertEqual(list_response.json(), [{"reference": "AGENT_API_KEY", "configured": True}])
        combined = set_response.text + list_response.text + agent_response.text + delete_response.text
        self.assertNotIn(secret, combined)
        self.assertNotIn("928374", combined)
        self.assertEqual(delete_response.json()["auth_state"], "unknown")
        self.assertFalse(secret_vault.has_key(f"agent:{agent_id}:agent_api_key"))

    async def test_manual_agent_update_disable_and_delete(self):
        path_one = f"C:\\lifecycle-one-{id(self)}.exe"
        path_two = f"C:\\lifecycle-two-{id(self)}.exe"
        inspection_one = {"state": "verified", "path": path_one, "version": "One 1.0", "evidence": {"resolved_path": path_one}}
        inspection_two = {"state": "verified", "path": path_two, "version": "Two 2.0", "evidence": {"resolved_path": path_two}}
        transport = httpx.ASGITransport(app=app)
        payload = {"name": "Lifecycle Agent", "executable": path_one, "version_probe_args": ["--version"], "invocation_args": ["{prompt}"]}
        with patch("core.ai_fleet.api.routes.system_scanner.inspect_manual", return_value=inspection_one):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                created_response = await client.post("/api/agents", json=payload)
        self.assertEqual(created_response.status_code, 200)
        created = created_response.json()
        self.created_ids.append(created["id"])

        with patch("core.ai_fleet.api.routes.system_scanner.inspect_manual", return_value=inspection_two):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                updated_response = await client.patch(
                    f"/api/agents/{created['id']}",
                    json={
                        "expected_revision": created["revision"],
                        "name": "Lifecycle Agent Updated",
                        "executable": path_two,
                        "version_probe_args": ["version"],
                        "invocation_args": ["run", "{prompt}"],
                        "capabilities": ["coding"],
                        "supports_pty": True,
                        "supports_interactive": True,
                        "environment_refs": ["LIFECYCLE_API_KEY"],
                    },
                )
        self.assertEqual(updated_response.status_code, 200)
        updated = updated_response.json()
        self.assertEqual(updated["name"], "Lifecycle Agent Updated")
        self.assertEqual(updated["detected_path"], path_two)
        self.assertIn("pty", updated["capabilities"])
        self.assertIn("interactive", updated["capabilities"])
        self.assertEqual(updated["environment_refs"], ["LIFECYCLE_API_KEY"])

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            disabled_response = await client.patch(f"/api/agents/{created['id']}", json={"expected_revision": updated["revision"], "user_enabled": False})
            invalid_env = await client.patch(f"/api/agents/{created['id']}", json={"expected_revision": disabled_response.json()["revision"], "environment_refs": ["KEY=value"]})
            deleted_response = await client.delete(f"/api/agents/{created['id']}")
        self.assertEqual(disabled_response.status_code, 200)
        self.assertFalse(disabled_response.json()["user_enabled"])
        self.assertEqual(invalid_env.status_code, 422)
        self.assertEqual(deleted_response.status_code, 200)
        self.assertTrue(deleted_response.json()["deleted"])
        self.created_ids.remove(created["id"])

    async def test_stale_agent_revision_is_rejected(self):
        agent_id = f"agent-revision-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(AgentRecord(id=agent_id, name="Revision Agent", cli_command=sys.executable, discovery_source="manual", revision=1))
            await session.commit()
        self.created_ids.append(agent_id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.patch(f"/api/agents/{agent_id}", json={"expected_revision": 1, "name": "First Writer"})
            stale = await client.patch(f"/api/agents/{agent_id}", json={"expected_revision": 1, "name": "Stale Writer"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["revision"], 2)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["code"], "stale_agent_revision")
        async with AsyncSessionLocal() as session:
            record = await session.get(AgentRecord, agent_id)
            self.assertEqual(record.name, "First Writer")

    async def test_manifest_agent_protects_configuration_and_delete(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            agents = await client.get("/api/agents")
            claude = next(item for item in agents.json() if item["id"] == "claude-code")
            disabled = await client.patch("/api/agents/claude-code", json={"expected_revision": claude["revision"], "user_enabled": False})
            forbidden_edit = await client.patch("/api/agents/claude-code", json={"expected_revision": disabled.json()["revision"], "name": "Changed"})
            forbidden_delete = await client.delete("/api/agents/claude-code")
            await client.patch("/api/agents/claude-code", json={"expected_revision": disabled.json()["revision"], "user_enabled": True})
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["user_enabled"])
        self.assertEqual(forbidden_edit.status_code, 409)
        self.assertEqual(forbidden_delete.status_code, 409)

    async def test_delete_referenced_manual_agent_retires_and_preserves_history(self):
        agent_id = f"agent-retire-{id(self)}"
        run_id = f"run-retire-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(AgentRecord(
                id=agent_id,
                name="Retired Agent",
                cli_command=sys.executable,
                detected_path=sys.executable,
                discovery_source="manual",
                discovery_state="verified",
                status="ready",
            ))
            from core.ai_fleet.storage.models import TaskRun

            session.add(TaskRun(id=run_id, prompt="history", selected_agent_id=agent_id, status="completed"))
            await session.commit()
        self.created_ids.append(agent_id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["retired"])
        async with AsyncSessionLocal() as session:
            record = await session.get(AgentRecord, agent_id)
            self.assertEqual(record.lifecycle_status, "retired")
            self.assertFalse(record.user_enabled)
            run = await session.get(TaskRun, run_id)
            self.assertEqual(run.selected_agent_id, agent_id)
            await session.delete(run)
            await session.commit()


if __name__ == "__main__":
    unittest.main()
