import json
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectBrainFactRecord, ProjectBrainFactRevisionRecord, ProjectRecord
from .audit import audit_service


SECTIONS = {"purpose", "users", "requirements", "brand", "architecture", "constraints", "quality", "production"}
TRUTH_STATES = {"unknown", "assumption", "proposed", "confirmed", "rejected"}
PROVENANCE = {"owner_declared", "user_declared", "observed", "imported", "model_proposed", "unknown"}
SOURCE_TYPES = {"user", "file", "run", "requirement", "decision", "research", "import", "system", "unknown"}


class ProjectBrainService:
    async def list(self, session: AsyncSession, project_id: str, section: Optional[str] = None) -> List[ProjectBrainFactRecord]:
        if not await session.get(ProjectRecord, project_id): raise DomainError("resource_not_found", message="Project was not found.")
        statement = select(ProjectBrainFactRecord).where(ProjectBrainFactRecord.project_id == project_id)
        if section:
            if section not in SECTIONS: raise DomainError("validation_failed", message="Brain section is invalid.")
            statement = statement.where(ProjectBrainFactRecord.section == section)
        return (await session.execute(statement.order_by(ProjectBrainFactRecord.section, ProjectBrainFactRecord.fact_key))).scalars().all()

    async def merge(self, session: AsyncSession, project_id: str, values: Dict[str, Any], expected_revision: Optional[int] = None) -> ProjectBrainFactRecord:
        project = await session.get(ProjectRecord, project_id)
        if not project or project.lifecycle_status != "active": raise DomainError("resource_not_found", message="Active project was not found.")
        normalized = self._validate(values)
        existing = (await session.execute(select(ProjectBrainFactRecord).where(ProjectBrainFactRecord.project_id == project_id, ProjectBrainFactRecord.section == normalized["section"], ProjectBrainFactRecord.fact_key == normalized["fact_key"]))).scalar_one_or_none()
        serialized = json.dumps(normalized["value"], sort_keys=True, separators=(",", ":"))
        if existing:
            unchanged = existing.value_json == serialized and all(getattr(existing, key) == normalized[key] for key in ["truth_state", "provenance", "source_type", "source_id", "confidence"])
            if unchanged: return existing
            if expected_revision is None:
                raise DomainError("resource_conflict", message="Brain fact differs from the current value; provide its revision to update.", details={"current": existing.to_dict()})
            if existing.revision != expected_revision: raise DomainError("stale_revision", details={"current_revision": existing.revision, "current": existing.to_dict()})
            record = existing; record.revision += 1
            for key in ["truth_state", "provenance", "source_type", "source_id", "confidence"]: setattr(record, key, normalized[key])
            record.value_json = serialized
        else:
            if expected_revision is not None: raise DomainError("resource_conflict", message="Cannot update a Brain fact that does not exist.")
            record = ProjectBrainFactRecord(id=f"brain-{uuid.uuid4().hex[:12]}", project_id=project_id, section=normalized["section"], fact_key=normalized["fact_key"], value_json=serialized, truth_state=normalized["truth_state"], provenance=normalized["provenance"], source_type=normalized["source_type"], source_id=normalized["source_id"], confidence=normalized["confidence"], revision=1)
            session.add(record); await session.flush()
        session.add(ProjectBrainFactRevisionRecord(id=f"brain-revision-{uuid.uuid4().hex[:12]}", fact_id=record.id, revision=record.revision, snapshot_json=json.dumps(record.to_dict(), sort_keys=True)))
        project.revision += 1
        await audit_service.append(session, action="project.brain_fact_merged", resource_type="project", resource_id=project_id, details={"actor": "local_system", "fact_id": record.id, "section": record.section, "fact_key": record.fact_key, "fact_revision": record.revision, "truth_state": record.truth_state, "provenance": record.provenance})
        await session.commit(); return record

    async def revisions(self, session: AsyncSession, fact_id: str) -> List[Dict[str, Any]]:
        if not await session.get(ProjectBrainFactRecord, fact_id): raise DomainError("resource_not_found", message="Brain fact was not found.")
        rows = (await session.execute(select(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == fact_id).order_by(ProjectBrainFactRevisionRecord.revision))).scalars().all()
        return [{"id": row.id, "fact_id": row.fact_id, "revision": row.revision, "snapshot": json.loads(row.snapshot_json), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]

    async def diff(self, session: AsyncSession, fact_id: str, from_revision: int, to_revision: int) -> Dict[str, Any]:
        rows = (await session.execute(select(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == fact_id, ProjectBrainFactRevisionRecord.revision.in_([from_revision, to_revision])))).scalars().all()
        by_revision = {row.revision: json.loads(row.snapshot_json) for row in rows}
        if set(by_revision) != {from_revision, to_revision}: raise DomainError("resource_not_found", message="One or more Brain fact revisions were not found.")
        before, after = by_revision[from_revision], by_revision[to_revision]
        keys = sorted(set(before) | set(after))
        changes = {key: {"before": before.get(key), "after": after.get(key)} for key in keys if before.get(key) != after.get(key)}
        return {"fact_id": fact_id, "from_revision": from_revision, "to_revision": to_revision, "changes": changes}

    async def restore(self, session: AsyncSession, fact_id: str, revision: int, expected_revision: int) -> ProjectBrainFactRecord:
        current = await session.get(ProjectBrainFactRecord, fact_id)
        snapshot_row = (await session.execute(select(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == fact_id, ProjectBrainFactRevisionRecord.revision == revision))).scalar_one_or_none()
        if not current or not snapshot_row: raise DomainError("resource_not_found", message="Brain fact or revision was not found.")
        if current.revision != expected_revision: raise DomainError("stale_revision", details={"current_revision": current.revision})
        snapshot = json.loads(snapshot_row.snapshot_json)
        for field, key in [("value_json", "value"), ("truth_state", "truth_state"), ("provenance", "provenance"), ("source_type", "source_type"), ("source_id", "source_id"), ("confidence", "confidence")]:
            setattr(current, field, json.dumps(snapshot[key], sort_keys=True, separators=(",", ":")) if field == "value_json" else snapshot.get(key))
        current.revision += 1
        session.add(ProjectBrainFactRevisionRecord(id=f"brain-revision-{uuid.uuid4().hex[:12]}", fact_id=fact_id, revision=current.revision, snapshot_json=json.dumps(current.to_dict(), sort_keys=True)))
        await audit_service.append(session, action="project.brain_fact_restored", resource_type="project", resource_id=current.project_id, details={"actor": "local_system", "fact_id": fact_id, "restored_from_revision": revision, "fact_revision": current.revision})
        await session.commit(); return current

    def _validate(self, values: Dict[str, Any]) -> Dict[str, Any]:
        section = values["section"]; key = values["fact_key"].strip().lower(); truth = values["truth_state"]; provenance = values["provenance"]; source_type = values["source_type"]; confidence = values.get("confidence")
        if section not in SECTIONS or not re.fullmatch(r"[a-z][a-z0-9._-]{1,127}", key) or truth not in TRUTH_STATES or provenance not in PROVENANCE or source_type not in SOURCE_TYPES or confidence is not None and not 0 <= confidence <= 1:
            raise DomainError("validation_failed", message="Project Brain fact metadata is invalid.")
        serialized = json.dumps(values.get("value"), sort_keys=True)
        if len(serialized.encode()) > 100000: raise DomainError("validation_failed", message="Project Brain fact value is too large.")
        if truth == "unknown" and values.get("value") is not None: raise DomainError("validation_failed", message="Unknown Brain facts must have a null value.")
        return {"section": section, "fact_key": key, "value": values.get("value"), "truth_state": truth, "provenance": provenance, "source_type": source_type, "source_id": values.get("source_id"), "confidence": confidence}


project_brain_service = ProjectBrainService()
