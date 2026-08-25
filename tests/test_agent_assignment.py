import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.services.agent_assignment import AgentAssignmentService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, OrchestrationTaskRecord, ProjectRecord, WorkspaceRecord


class AgentAssignmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"assign-project-{id(self)}"
        self.workspace_id = f"assign-workspace-{id(self)}"
        self.task_id = f"assign-task-{id(self)}"
        self.agent_ids = [f"assign-agent-{id(self)}-{index}" for index in range(4)]
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Assign", slug=f"assign-{id(self)}", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Workspace", path="D:/assign", permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(OrchestrationTaskRecord(id=self.task_id, project_id=self.project_id, task_type="build", title="Build", acceptance_json='[{"criterion_id":"x"}]', executor_needs_json=json.dumps({"capabilities": ["coding", "shell"]}), state="ready"))
            common = {"tool_kind": "agent", "user_enabled": True, "lifecycle_status": "active", "discovery_state": "verified", "status": "ready", "auth_state": "not_required", "permission_profile": "developer"}
            session.add(AgentRecord(id=self.agent_ids[0], name="AAA Valid", cli_command="valid", capabilities='["coding","shell"]', discovery_source="manual", **common))
            session.add(AgentRecord(id=self.agent_ids[1], name="Missing", cli_command="missing", capabilities='["coding"]', discovery_source="manual", **common))
            session.add(AgentRecord(id=self.agent_ids[2], name="Auth", cli_command="auth", capabilities='["coding","shell"]', discovery_source="manual", **{**common, "auth_state": "unknown"}))
            session.add(AgentRecord(id=self.agent_ids[3], name="Unavailable", cli_command="bad", capabilities='["coding","shell"]', discovery_source="manual", **{**common, "status": "broken"}))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AgentRecord).where(AgentRecord.id.in_(self.agent_ids)))
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id == self.task_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()

    async def test_only_verified_capable_permission_compatible_agent_is_assigned(self):
        async with AsyncSessionLocal() as session:
            result = await AgentAssignmentService().assign(session, self.task_id, self.workspace_id)
        self.assertEqual(result["selected_agent"]["id"], self.agent_ids[0])
        blockers = {item["agent_id"]: item["blockers"] for item in result["rejected"]}
        self.assertIn("missing_capability:shell", blockers[self.agent_ids[1]])
        self.assertIn("auth_unverified", blockers[self.agent_ids[2]])
        self.assertIn("agent_unavailable", blockers[self.agent_ids[3]])


if __name__ == "__main__":
    unittest.main()
