import json
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import BlueprintProposalRecord, BlueprintProposalRevisionRecord, ProjectRecord
from .requirements import RequirementService


class BlueprintApprovalService:
    def __init__(self): self._requirements = RequirementService()
    async def list(self, session: AsyncSession, project_id: str):
        from sqlalchemy import select
        return (await session.execute(select(BlueprintProposalRecord).where(BlueprintProposalRecord.project_id == project_id).order_by(BlueprintProposalRecord.created_at.desc()))).scalars().all()
    async def create(self, session: AsyncSession, project_id: str, proposal: Dict[str, Any]) -> BlueprintProposalRecord:
        if not await session.get(ProjectRecord, project_id) or not proposal.get("approval_required") or proposal.get("implementation_started") or not isinstance(proposal.get("requirements"), list) or not isinstance(proposal.get("questions"), list): raise DomainError("validation_failed", message="Blueprint proposal is invalid.")
        record = BlueprintProposalRecord(id=f"blueprint-{uuid.uuid4().hex[:12]}", project_id=project_id, template_id=proposal["template_id"], template_version=proposal["template_version"], status="proposed", content_json=json.dumps(proposal), revision=1)
        session.add(record); await session.flush(); await self._snapshot(session, record); await session.commit(); return record
    async def edit(self, session: AsyncSession, proposal_id: str, content: Dict[str, Any], expected_revision: int) -> BlueprintProposalRecord:
        record = await session.get(BlueprintProposalRecord, proposal_id)
        if not record: raise DomainError("resource_not_found", message="Blueprint proposal was not found.")
        if record.status != "proposed": raise DomainError("resource_conflict", message="Approved blueprint is immutable.")
        if record.revision != expected_revision: raise DomainError("stale_revision", details={"current_revision": record.revision})
        if not isinstance(content.get("requirements"), list) or not isinstance(content.get("questions"), list): raise DomainError("validation_failed", message="Blueprint proposal content is invalid.")
        content["owner_edited"] = True; content["approval_required"] = True; content["implementation_started"] = False
        record.content_json = json.dumps(content); record.revision += 1; await self._snapshot(session, record); await session.commit(); return record
    async def approve(self, session: AsyncSession, proposal_id: str, actor: str, expected_revision: int) -> Dict[str, Any]:
        record = await session.get(BlueprintProposalRecord, proposal_id)
        if not record: raise DomainError("resource_not_found", message="Blueprint proposal was not found.")
        if record.status != "proposed" or record.revision != expected_revision: raise DomainError("resource_conflict", message="Blueprint proposal is not current and proposed.")
        content = json.loads(record.content_json); requirement_ids = []
        for item in content["requirements"]:
            created = await self._requirements.create(session, record.project_id, {"title": item["title"], "description": item["description"], "requirement_type": item["requirement_type"], "source_type": "system", "source_id": proposal_id, "truth_state": "proposed", "priority": item["priority"], "acceptance": item.get("acceptance", []), "evidence": [{"type": "blueprint_proposal", "id": proposal_id}], "owner": actor})
            requirement_ids.append(created.id)
        record.status = "approved"; record.approved_by = actor; record.approved_at = datetime.utcnow(); record.revision += 1; await self._snapshot(session, record); await session.commit()
        return {"proposal": record.to_dict(), "requirement_ids": requirement_ids, "questions": content["questions"], "owner_changes_retained": bool(content.get("owner_edited"))}
    async def _snapshot(self, session, record): session.add(BlueprintProposalRevisionRecord(id=f"blueprint-revision-{uuid.uuid4().hex[:12]}", proposal_id=record.id, revision=record.revision, snapshot_json=json.dumps(record.to_dict(), sort_keys=True)))


blueprint_approval_service = BlueprintApprovalService()
