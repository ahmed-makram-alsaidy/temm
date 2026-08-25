import uuid
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..filesystem import PathPolicyError, path_policy
from ..storage.models import ProjectRecord, ProjectWorkspaceLinkRecord, WorkspaceRecord
from .audit import audit_service


ROLES = {"primary", "secondary", "assets", "docs", "tests", "output"}


class ProjectWorkspaceService:
    async def bind(self, session: AsyncSession, project_id: str, workspace_id: str, role: str) -> ProjectWorkspaceLinkRecord:
        project = await session.get(ProjectRecord, project_id); workspace = await session.get(WorkspaceRecord, workspace_id)
        if not project or not workspace: raise DomainError("resource_not_found", message="Project or approved workspace was not found.")
        if project.lifecycle_status != "active" or role not in ROLES: raise DomainError("validation_failed", message="Project workspace role or lifecycle is invalid.")
        try: path_policy.existing_directory(workspace.path)
        except PathPolicyError as exc: raise DomainError("validation_failed", message="Workspace path is no longer available.") from exc
        existing = (await session.execute(select(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == project_id, ProjectWorkspaceLinkRecord.workspace_id == workspace_id))).scalar_one_or_none()
        if existing: raise DomainError("resource_conflict", message="Workspace is already linked to this project.")
        if role == "primary" and (await session.execute(select(ProjectWorkspaceLinkRecord.id).where(ProjectWorkspaceLinkRecord.project_id == project_id, ProjectWorkspaceLinkRecord.role == "primary"))).scalar_one_or_none():
            raise DomainError("resource_conflict", message="Project already has a primary workspace.")
        record = ProjectWorkspaceLinkRecord(id=f"project-workspace-{uuid.uuid4().hex[:12]}", project_id=project_id, workspace_id=workspace_id, role=role)
        session.add(record); project.revision += 1
        await audit_service.append(session, action="project.workspace_bound", resource_type="project", resource_id=project_id, details={"actor": "local_system", "workspace_id": workspace_id, "role": role, "revision": project.revision, "permission_profile": workspace.permission_profile})
        await session.commit(); return record

    async def list(self, session: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
        if not await session.get(ProjectRecord, project_id): raise DomainError("resource_not_found", message="Project was not found.")
        links = (await session.execute(select(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == project_id).order_by(ProjectWorkspaceLinkRecord.role, ProjectWorkspaceLinkRecord.created_at))).scalars().all()
        result = []
        for link in links:
            workspace = await session.get(WorkspaceRecord, link.workspace_id)
            result.append({**link.to_dict(), "workspace": workspace.to_dict() if workspace else None})
        return result

    async def unbind(self, session: AsyncSession, project_id: str, workspace_id: str) -> None:
        link = (await session.execute(select(ProjectWorkspaceLinkRecord).where(ProjectWorkspaceLinkRecord.project_id == project_id, ProjectWorkspaceLinkRecord.workspace_id == workspace_id))).scalar_one_or_none()
        if not link: raise DomainError("resource_not_found", message="Project workspace link was not found.")
        project = await session.get(ProjectRecord, project_id)
        await session.delete(link); project.revision += 1
        await audit_service.append(session, action="project.workspace_unbound", resource_type="project", resource_id=project_id, details={"actor": "local_system", "workspace_id": workspace_id, "role": link.role, "revision": project.revision})
        await session.commit()


project_workspace_service = ProjectWorkspaceService()
