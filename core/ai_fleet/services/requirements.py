import json
import uuid
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectRecord, ProjectRequirementRecord, ProjectRequirementRevisionRecord
from .audit import audit_service


TYPES = {"functional", "nonfunctional", "constraint", "quality", "production", "security", "content", "asset"}
SOURCES = {"user", "brain", "decision", "research", "import", "system"}
TRUTH = {"unknown", "proposed", "confirmed", "rejected"}
PRIORITIES = {"must", "should", "could", "wont"}
TRANSITIONS = {"draft": {"approved", "rejected"}, "approved": {"blocked", "completed", "waived"}, "blocked": {"approved", "waived"}}


class RequirementService:
    async def create(self, session: AsyncSession, project_id: str, values: Dict[str, Any]) -> ProjectRequirementRecord:
        project = await session.get(ProjectRecord, project_id)
        if not project or project.lifecycle_status != "active": raise DomainError("resource_not_found", message="Active project was not found.")
        self._validate(values)
        if values.get("parent_id"):
            parent = await session.get(ProjectRequirementRecord, values["parent_id"])
            if not parent or parent.project_id != project_id: raise DomainError("validation_failed", message="Requirement parent is invalid.")
        record = ProjectRequirementRecord(id=f"requirement-{uuid.uuid4().hex[:12]}", project_id=project_id, parent_id=values.get("parent_id"), title=values["title"].strip(), description=values.get("description", ""), requirement_type=values["requirement_type"], source_type=values["source_type"], source_id=values.get("source_id"), truth_state=values["truth_state"], priority=values["priority"], status="draft", acceptance_json=json.dumps(values.get("acceptance", [])), evidence_json=json.dumps(values.get("evidence", [])), owner=values.get("owner"), revision=1)
        session.add(record); await session.flush(); await self._snapshot(session, record)
        await audit_service.append(session, action="project.requirement_created", resource_type="project", resource_id=project_id, details={"actor": "local_system", "requirement_id": record.id, "revision": 1})
        await session.commit(); return record

    async def list(self, session: AsyncSession, project_id: str) -> List[ProjectRequirementRecord]:
        return (await session.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == project_id).order_by(ProjectRequirementRecord.created_at))).scalars().all()

    async def update(self, session: AsyncSession, requirement_id: str, changes: Dict[str, Any], expected_revision: int) -> ProjectRequirementRecord:
        record = await self._get(session, requirement_id)
        if record.revision != expected_revision: raise DomainError("stale_revision", details={"current_revision": record.revision})
        if record.status not in {"draft", "approved", "blocked"}: raise DomainError("resource_conflict", message="Settled requirement cannot be edited.")
        for field in ["title", "description", "priority", "owner", "truth_state"]:
            if field in changes: setattr(record, field, changes[field])
        if "acceptance" in changes: record.acceptance_json = json.dumps(changes["acceptance"])
        if "evidence" in changes: record.evidence_json = json.dumps(changes["evidence"])
        record.revision += 1; await self._snapshot(session, record); await session.commit(); return record

    async def transition(self, session: AsyncSession, requirement_id: str, target: str, actor: str, rationale: str = "") -> ProjectRequirementRecord:
        record = await self._get(session, requirement_id)
        if target not in TRANSITIONS.get(record.status, set()): raise DomainError("resource_conflict", message="Requirement transition is invalid.")
        if target == "approved" and (record.truth_state != "confirmed" or not json.loads(record.acceptance_json)): raise DomainError("validation_failed", message="Approved requirement needs confirmed truth and acceptance criteria.")
        if target == "completed" and not json.loads(record.evidence_json): raise DomainError("validation_failed", message="Completed requirement needs evidence.")
        if target == "waived":
            if len(rationale.strip()) < 10: raise DomainError("validation_failed", message="Waiver requires a substantive rationale.")
            record.waiver_rationale = rationale.strip(); record.waived_by = actor
        record.status = target; record.revision += 1; await self._snapshot(session, record)
        await audit_service.append(session, action=f"project.requirement_{target}", resource_type="project", resource_id=record.project_id, details={"actor": actor, "requirement_id": record.id, "revision": record.revision, "waiver_rationale": rationale if target == "waived" else None})
        await session.commit(); return record

    async def record_measured_completion(self, session: AsyncSession, record: ProjectRequirementRecord, evidence: Dict[str, Any], actor: str = "completeness_reconciliation") -> bool:
        """Credit a requirement whose acceptance contract has been measured satisfied.

        `transition` is the only writer of `completed` and is reachable only from
        `POST /projects/requirements/{id}/transition`, so before this method no part of
        the engine could record that a requirement had been met - the fleet could
        measure a contract, dispatch against it, and prove every clause, and the
        requirement stayed `approved` for ever. `CompletionAssessmentService.assess`
        blocks on every requirement whose status is not `completed` or `waived`, so
        delivery readiness was unreachable by construction rather than by evidence.

        Production evidence on project-23a514f0c426, 2026-08-22 01:07: ten
        requirements, every one `approved`, every one carrying two to four typed
        evaluators, none of them creditable.

        This is the same rule `transition` enforces, reached from measurement instead
        of from a human: completion needs evidence, and the caller's evidence is what
        makes it legal. An empty measurement credits nothing. The transition table
        still decides legality, so a `draft` requirement cannot be completed without
        being approved first and a `blocked` one keeps its blockage; the caller learns
        that from the returned False rather than from an exception, because a
        requirement that is satisfied but not creditable is a normal state of the graph
        and not an error. Committing is left to the caller so this can take part in a
        reconciliation pass's transaction.
        """
        if not evidence or "completed" not in TRANSITIONS.get(record.status, set()):
            return False
        items = json.loads(record.evidence_json or "[]")
        items.append(evidence)
        record.evidence_json = json.dumps(items)
        record.status = "completed"
        record.revision += 1
        await self._snapshot(session, record)
        await audit_service.append(session, action="project.requirement_completed", resource_type="project", resource_id=record.project_id, details={"actor": actor, "requirement_id": record.id, "revision": record.revision, "evidence": evidence})
        await session.flush()
        return True

    async def _get(self, session, requirement_id):
        record = await session.get(ProjectRequirementRecord, requirement_id)
        if not record: raise DomainError("resource_not_found", message="Requirement was not found.")
        return record
    async def _snapshot(self, session, record): session.add(ProjectRequirementRevisionRecord(id=f"requirement-revision-{uuid.uuid4().hex[:12]}", requirement_id=record.id, revision=record.revision, snapshot_json=json.dumps(record.to_dict(), sort_keys=True)))
    def _validate(self, values):
        if values["requirement_type"] not in TYPES or values["source_type"] not in SOURCES or values["truth_state"] not in TRUTH or values["priority"] not in PRIORITIES or not isinstance(values.get("acceptance", []), list) or not isinstance(values.get("evidence", []), list): raise DomainError("validation_failed", message="Requirement metadata is invalid.")


requirement_service = RequirementService()
