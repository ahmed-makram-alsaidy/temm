import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..permissions import permission_policy
from ..storage.models import AgentRecord, OrchestrationTaskRecord, WorkspaceRecord


class AgentAssignmentService:
    async def assign(self, session: AsyncSession, task_id: str, workspace_id: str) -> dict:
        task = await session.get(OrchestrationTaskRecord, task_id)
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not task or not workspace:
            raise DomainError("resource_not_found", message="Task or workspace was not found.")
        needs = json.loads(task.executor_needs_json or "{}")
        required = set(needs.get("capabilities", []))
        requested_agent_id = needs.get("agent_id")
        route_capabilities = {"text_generation", "multi_file_edit", "dependency_management", "command_execution", "debugging", "project_refactor", "quality_gate", "reasoning", "research"}
        agent_required = required - route_capabilities
        agents = (await session.execute(select(AgentRecord))).scalars().all()
        eligible = []
        rejected = []
        for agent in agents:
            if requested_agent_id and agent.id != requested_agent_id:
                continue
            blockers = []
            capabilities = set(agent.to_dict().get("capabilities", []))
            if agent.tool_kind != "agent" or not agent.user_enabled or agent.lifecycle_status != "active" or agent.discovery_state != "verified" or agent.status != "ready":
                blockers.append("agent_unavailable")
            if agent.auth_state not in {"not_required", "verified"}:
                blockers.append("auth_unverified")
            missing = sorted(agent_required - capabilities)
            blockers.extend(f"missing_capability:{item}" for item in missing)
            try:
                permission_policy.enforce_agent_workspace(agent.permission_profile, workspace.permission_profile, sorted(agent_required))
            except PermissionError:
                blockers.append("permission_incompatible")
            if blockers:
                rejected.append({"agent_id": agent.id, "blockers": sorted(set(blockers))})
            else:
                eligible.append(agent)
        if not eligible:
            raise DomainError("execution_unavailable", message="No verified compatible Agent is available.", details={"rejected": rejected})
        eligible.sort(key=lambda agent: (agent.discovery_source != "manual", agent.name.lower(), agent.id))
        selected = eligible[0]
        return {"task_id": task_id, "workspace_id": workspace_id, "selected_agent": selected.to_dict(), "required_capabilities": sorted(required), "alternatives": [agent.to_dict() for agent in eligible[1:]], "rejected": rejected, "assignment_basis": "verified_capability_permission_match"}


agent_assignment_service = AgentAssignmentService()
