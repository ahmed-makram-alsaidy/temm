import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.api.routes import _capability_blockers
from core.ai_fleet.engine import execution_readiness as readiness
from core.ai_fleet.main import app
from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, AuditRecord, OrchestrationTaskRecord, ProjectRecord, ProjectWorkspaceLinkRecord, WorkspaceRecord


class ProjectExecutionReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.project_id = f"readiness-project-{id(self)}"
        self.workspace_id = f"readiness-workspace-{id(self)}"
        self.task_id = f"readiness-task-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Readiness", slug=f"readiness-{id(self)}", purpose="Create a small verified artifact", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Readiness folder", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(OrchestrationTaskRecord(id=self.task_id, project_id=self.project_id, task_type="requirement_implementation", title="Create proof", description="Create only proof.txt containing exactly OK.", acceptance_json="[]", executor_needs_json=json.dumps({"capabilities": ["coding"]}), state="planned"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == self.project_id))
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()

    async def test_readiness_requires_project_binding_then_preserves_it(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            before = await client.get(f"/api/projects/{self.project_id}/execution-readiness")
            self.assertEqual(before.status_code, 200, before.text)
            self.assertFalse(before.json()["ready"])
            self.assertEqual(before.json()["blockers"][0]["code"], "workspace_required")
            bound = await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_id, "role": "primary"})
            self.assertEqual(bound.status_code, 200, bound.text)
            listing = await client.get(f"/api/projects/{self.project_id}/workspaces")
            self.assertEqual(listing.json()[0]["workspace_id"], self.workspace_id)
            after = await client.get(f"/api/projects/{self.project_id}/execution-readiness")
            self.assertEqual(after.status_code, 200, after.text)
            self.assertEqual(after.json()["workspace"]["id"], self.workspace_id)
            self.assertNotEqual(after.json()["blockers"][0]["code"] if after.json()["blockers"] else None, "workspace_required")

    async def test_readiness_reports_the_persisted_task_capability_contract(self):
        """The endpoint must hand the dispatcher's own contract to the gate."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            await client.post(f"/api/projects/{self.project_id}/workspaces", json={"workspace_id": self.workspace_id, "role": "primary"})
            payload = (await client.get(f"/api/projects/{self.project_id}/execution-readiness")).json()
        self.assertEqual(payload["task_id"], self.task_id)
        self.assertEqual(payload["required_capabilities"], ["coding"])
        self.assertEqual(payload["capability_basis"], "task_contract")
        self.assertEqual(payload["preflight"]["required_capabilities"], ["coding"])


class ProjectTaskContractReadinessTests(unittest.IsolatedAsyncioTestCase):
    """Readiness must gate on the contract the dispatcher will use, not on the prose.

    A persisted task states what its executor has to be able to do. The gate used to
    throw that away and re-derive a capability from the task's wording, so a task whose
    description reads like reasoning demanded `reasoning` while the dispatcher demanded
    `coding`. No CLI declares `reasoning`, so an approved project with a verified,
    permitted, authenticated coding agent bound to an approved folder could never become
    ready - the gate refused a route the dispatcher would have accepted.
    """

    def _agent(self, capabilities):
        return AgentRecord(
            id="slice2-agent", name="Slice2 Agent", cli_command="C:\\slice2.exe", detected_path="C:\\slice2.exe",
            tool_kind="agent", user_enabled=True, lifecycle_status="active", auth_state="verified",
            discovery_state="verified", status="ready", permission_profile="developer",
            capabilities=json.dumps(capabilities), supports_pty=False, supports_interactive=False,
            discovery_source="manifest", revision=1,
        )

    async def _preflight(self, agent, **kwargs):
        workspace = WorkspaceRecord(id="slice2-ws", name="Slice2", path="C:\\slice2", permission_profile="developer", allowed_shells='["powershell"]', is_default=True)

        class _Result:
            def __init__(self, rows): self._rows = rows
            def scalars(self): return self
            def all(self): return self._rows

        class _Session:
            async def execute(self, statement):
                entity = statement.column_descriptions[0]["entity"]
                return _Result([agent] if entity is AgentRecord else [workspace] if entity is WorkspaceRecord else [])

        class _SessionFactory:
            async def __aenter__(self): return _Session()
            async def __aexit__(self, *exc_info): return False

        scan = {"configured_providers": [], "discovered_tools": [], "ollama_status": {"running": False}}
        # The prose reading of this prompt is `reasoning`; the task contract says `coding`.
        recommendation = {"task_analysis": {"category": "reasoning"}, "selected_model": {"id": "none"}, "fallback_chain": []}
        with unittest.mock.patch.object(readiness, "AsyncSessionLocal", _SessionFactory), \
                unittest.mock.patch.object(readiness, "host_capacity", return_value={"sufficient": True, "detail": None, "measurable": True, "pressure": False}), \
                unittest.mock.patch.object(readiness.system_scanner, "scan_system", new=unittest.mock.AsyncMock(return_value=scan)), \
                unittest.mock.patch.object(readiness.model_router, "recommend_model", new=unittest.mock.AsyncMock(return_value=recommendation)):
            return await readiness.build_execution_preflight("Create only proof.txt containing exactly OK.", workspace_id="slice2-ws", **kwargs)

    async def test_task_contract_decides_the_required_capability(self):
        report = await self._preflight(self._agent(["general", "coding", "file_read", "file_write"]), required_capabilities=["coding"])
        self.assertTrue(report["can_execute"], report["blockers"])
        self.assertEqual(report["required_capabilities"], ["coding"])
        self.assertEqual(report["capability_basis"], "task_contract")
        self.assertEqual(report["route_decision"]["selected_route"]["route_id"], "agent:slice2-agent")

    async def test_a_capability_the_agent_does_not_serve_still_blocks(self):
        report = await self._preflight(self._agent(["general", "file_read"]), required_capabilities=["coding"])
        self.assertFalse(report["can_execute"])
        self.assertEqual(report["capability_basis"], "task_contract")
        self.assertIsNone(report["route_decision"])

    async def test_declared_general_serves_a_derived_category_for_an_ad_hoc_prompt(self):
        """Without a contract the prose category still applies, and the candidate must
        publish the same answer `_agent_supports` gives, or selection rejects a route the
        rest of the engine considers eligible."""
        report = await self._preflight(self._agent(["general", "coding"]))
        self.assertEqual(report["capability_basis"], "prompt_analysis")
        self.assertEqual(report["required_capabilities"], ["reasoning"])
        self.assertTrue(report["can_execute"], report["blockers"])


class GateAndDispatcherAgreementTests(unittest.IsolatedAsyncioTestCase):
    """The route the gate promises has to be the route the dispatcher will take.

    No OpenCode-discovered model route exists in this database, so the model selection
    the dispatcher tries first finds nothing with current capability evidence. Before the
    fix that refused the dispatch outright; the verified local CLI the gate had already
    offered is now used instead, and is reported as such.
    """

    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"agree-project-{id(self)}"
        self.task_id = f"agree-task-{id(self)}"
        self.agent_id = f"agree-agent-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Agree", slug=f"agree-{id(self)}", purpose="proof", project_type="software", owner="local"))
            session.add(AgentRecord(id=self.agent_id, name="Agree CLI", adapter_id=self.agent_id, cli_command="C:\\agree.exe", detected_path="C:\\agree.exe", tool_kind="agent", user_enabled=True, lifecycle_status="active", auth_state="verified", discovery_state="verified", status="ready", permission_profile="developer", capabilities=json.dumps(["coding"]), discovery_source="manifest"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(AgentRecord).where(AgentRecord.id == self.agent_id))
            await session.commit()

    def _task(self, needs):
        return OrchestrationTaskRecord(id=self.task_id, project_id=self.project_id, task_type="requirement_implementation", title="Create proof", description="Create only proof.txt", acceptance_json="[]", executor_needs_json=json.dumps(needs), state="planned")

    async def test_a_verified_agent_is_the_route_when_the_task_names_only_a_capability(self):
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            decision = await ProjectDispatcherService(None)._select_model(session, self._task({"capabilities": ["coding"]}), agent)
        self.assertEqual(decision["provider"], self.agent_id)
        self.assertEqual(decision["selection_basis"], "verified_capability_agent")
        self.assertEqual(decision["required_capabilities"], ["coding"])
        # A model that took no part in the execution must not be recorded against it.
        self.assertIsNone(decision["model_id"])
        self.assertIsNone(decision["model"])

    async def test_an_explicitly_named_agent_keeps_its_own_basis(self):
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            decision = await ProjectDispatcherService(None)._select_model(session, self._task({"capabilities": ["coding"], "agent_id": self.agent_id}), agent)
        self.assertEqual(decision["selection_basis"], "explicit_executor_agent")

    async def test_without_any_agent_an_unavailable_model_route_is_still_refused(self):
        """The fallback must not become a way for a modelless dispatch to look fine."""
        from core.ai_fleet.errors import DomainError
        async with AsyncSessionLocal() as session:
            with self.assertRaises(DomainError) as raised:
                await ProjectDispatcherService(None)._select_model(session, self._task({"capabilities": ["coding"]}), None)
        self.assertEqual(raised.exception.code, "execution_unavailable")


class ContextualBlockerTests(unittest.TestCase):
    """An owner is told which capability is missing, not which six brands failed."""

    def test_sign_in_blockers_collapse_into_one_capability_action(self):
        preflight = {"blockers": [
            {"code": "agent_auth_unverified", "title": "Claude Code", "detail": "Authentication is required but has not been verified."},
            {"code": "provider_not_configured", "title": "GPT-4o", "detail": "Provider credentials are not configured."},
        ]}
        blockers = _capability_blockers(["coding"], preflight)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["code"], "capability_signin_required")
        self.assertEqual(blockers[0]["title"], "Coding capability required")
        self.assertEqual(blockers[0]["action_target"], "fleet")
        self.assertEqual(len(blockers[0]["routes"]), 2, "The route-level record stays available underneath.")

    def test_a_host_blocker_is_never_hidden_behind_a_capability_message(self):
        preflight = {"blockers": [
            {"code": "agent_auth_unverified", "title": "Claude Code", "detail": "x"},
            {"code": "host_capacity_unavailable", "title": "Host out of memory", "detail": "y"},
        ]}
        self.assertEqual(_capability_blockers(["coding"], preflight)[0]["code"], "host_capacity_unavailable")

    def test_no_blockers_stay_no_blockers(self):
        self.assertEqual(_capability_blockers(["coding"], {"blockers": []}), [])


if __name__ == "__main__":
    unittest.main()
