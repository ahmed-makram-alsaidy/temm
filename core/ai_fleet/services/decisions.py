import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectDecisionRecord, ProjectDecisionRevisionRecord, ProjectRecord
from .audit import audit_service


SCOPES = {"project", "component", "requirement"}
SOURCES = {"user", "brain", "requirement", "research", "import", "system"}


class DecisionService:
    async def create(self, session: AsyncSession, project_id: str, values: Dict[str, Any], supersedes_id: Optional[str] = None) -> ProjectDecisionRecord:
        project = await session.get(ProjectRecord, project_id)
        if not project or project.lifecycle_status != "active": raise DomainError("resource_not_found", message="Active project was not found.")
        if values["scope_type"] not in SCOPES or values["source_type"] not in SOURCES or not isinstance(values.get("rule"), dict): raise DomainError("validation_failed", message="Decision metadata is invalid.")
        if supersedes_id:
            previous = await session.get(ProjectDecisionRecord, supersedes_id)
            if not previous or previous.project_id != project_id or previous.status != "approved": raise DomainError("resource_conflict", message="Only an approved project decision can be superseded.")
        record = ProjectDecisionRecord(id=f"decision-{uuid.uuid4().hex[:12]}", project_id=project_id, scope_type=values["scope_type"], scope_id=values.get("scope_id"), statement=values["statement"].strip(), rationale=values["rationale"].strip(), impact=values["impact"].strip(), rule_json=json.dumps(values["rule"], sort_keys=True), source_type=values["source_type"], source_id=values.get("source_id"), status="proposed", supersedes_id=supersedes_id, revision=1)
        session.add(record); await session.flush(); await self._snapshot(session, record)
        await audit_service.append(session, action="project.decision_created", resource_type="project", resource_id=project_id, details={"actor": "local_system", "decision_id": record.id, "scope_type": record.scope_type, "scope_id": record.scope_id, "supersedes_id": supersedes_id})
        await session.commit(); return record

    async def list(self, session: AsyncSession, project_id: str, status: Optional[str] = None, scope_type: Optional[str] = None, scope_id: Optional[str] = None) -> List[ProjectDecisionRecord]:
        statement = select(ProjectDecisionRecord).where(ProjectDecisionRecord.project_id == project_id)
        if status: statement = statement.where(ProjectDecisionRecord.status == status)
        if scope_type: statement = statement.where(ProjectDecisionRecord.scope_type == scope_type)
        if scope_id: statement = statement.where(ProjectDecisionRecord.scope_id == scope_id)
        return (await session.execute(statement.order_by(ProjectDecisionRecord.created_at, ProjectDecisionRecord.id))).scalars().all()

    async def context(self, session: AsyncSession, project_id: str, component: Optional[str] = None, requirement_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        rows = (await session.execute(select(ProjectDecisionRecord).where(ProjectDecisionRecord.project_id == project_id).order_by(ProjectDecisionRecord.created_at, ProjectDecisionRecord.id))).scalars().all()
        requirements = set(requirement_ids or []); selected = []; excluded = []
        for row in rows:
            reason = None
            if row.status != "approved": excluded.append({"decision_id": row.id, "reason": f"status_{row.status}"}); continue
            if row.scope_type == "project": reason = "project_scope"
            elif row.scope_type == "component" and row.scope_id == component: reason = "component_scope"
            elif row.scope_type == "requirement" and row.scope_id in requirements: reason = "requirement_scope"
            if reason: selected.append({"decision": row.to_dict(), "reason": reason})
            else: excluded.append({"decision_id": row.id, "reason": "scope_not_relevant"})
        order = {"project_scope": 0, "component_scope": 1, "requirement_scope": 2}; selected.sort(key=lambda item: (order[item["reason"]], item["decision"]["id"]))
        return {"selected": selected, "excluded": excluded, "query": {"project_id": project_id, "component": component, "requirement_ids": sorted(requirements)}, "selector_version": "1.0"}

    async def decide(self, session: AsyncSession, decision_id: str, action: str, actor: str) -> ProjectDecisionRecord:
        record = await session.get(ProjectDecisionRecord, decision_id)
        if not record: raise DomainError("resource_not_found", message="Decision was not found.")
        if record.status != "proposed" or action not in {"approve", "reject"}: raise DomainError("resource_conflict", message="Decision transition is invalid.")
        if action == "approve":
            conflict = (await session.execute(select(ProjectDecisionRecord).where(ProjectDecisionRecord.project_id == record.project_id, ProjectDecisionRecord.scope_type == record.scope_type, ProjectDecisionRecord.scope_id == record.scope_id, ProjectDecisionRecord.status == "approved", ProjectDecisionRecord.id != record.id))).scalars().first()
            if conflict and record.supersedes_id != conflict.id: raise DomainError("resource_conflict", message="An approved decision already exists for this scope; explicitly supersede it.", details={"decision_id": conflict.id})
            if record.supersedes_id:
                previous = await session.get(ProjectDecisionRecord, record.supersedes_id)
                if not previous or previous.status != "approved": raise DomainError("resource_conflict", message="Superseded decision is no longer active.")
                previous.status = "superseded"; previous.revision += 1; await self._snapshot(session, previous)
            record.status = "approved"; record.approved_by = actor; record.approved_at = datetime.utcnow()
        else: record.status = "rejected"
        record.revision += 1; await self._snapshot(session, record)
        await audit_service.append(session, action=f"project.decision_{action}d", resource_type="project", resource_id=record.project_id, details={"actor": actor, "decision_id": record.id, "revision": record.revision, "supersedes_id": record.supersedes_id})
        await session.commit(); return record

    async def _snapshot(self, session: AsyncSession, record: ProjectDecisionRecord) -> None:
        session.add(ProjectDecisionRevisionRecord(id=f"decision-revision-{uuid.uuid4().hex[:12]}", decision_id=record.id, revision=record.revision, snapshot_json=json.dumps(record.to_dict(), sort_keys=True)))


decision_service = DecisionService()
