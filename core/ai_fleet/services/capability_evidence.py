import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import CAPABILITIES
from ..errors import DomainError
from ..storage.models import ModelCapabilityEvidenceRecord, ModelRecord
from .audit import audit_service


PRECEDENCE = {"execution_measured": 5, "benchmark_measured": 4, "provider_reported": 3, "user_declared": 2, "catalog_declared": 1}
SOURCE_TYPES = {"execution", "benchmark", "provider", "user", "catalog"}


class CapabilityEvidenceService:
    async def record(self, session: AsyncSession, model_id: str, values: Dict[str, Any], allowed_provenance: Optional[set[str]] = None) -> ModelCapabilityEvidenceRecord:
        model = await session.get(ModelRecord, model_id)
        if not model:
            raise DomainError("resource_not_found", message="Model was not found.")
        capability = values["capability"]
        provenance = values["provenance"]
        source_type = values["source_type"]
        if capability not in CAPABILITIES or provenance not in PRECEDENCE or source_type not in SOURCE_TYPES:
            raise DomainError("validation_failed", message="Capability evidence metadata is invalid.")
        if allowed_provenance is not None and provenance not in allowed_provenance:
            raise DomainError("permission_denied", message="This evidence provenance cannot be asserted through this interface.")
        score = values.get("score")
        if score is not None and (not values["supported"] or not 0 <= score <= 100):
            raise DomainError("validation_failed", message="Capability score must be 0-100 for supported capabilities.")
        observed_at = values["observed_at"]
        expires_at = values.get("expires_at")
        if expires_at and expires_at <= observed_at:
            raise DomainError("validation_failed", message="Capability evidence expiry must follow observation time.")
        record = ModelCapabilityEvidenceRecord(
            id=f"cap-{uuid.uuid4().hex[:12]}",
            model_id=model_id,
            capability=capability,
            supported=values["supported"],
            score=score,
            provenance=provenance,
            source_type=source_type,
            source_uri=values.get("source_uri", ""),
            evidence=json.dumps(values.get("evidence", {})),
            observed_at=observed_at,
            expires_at=expires_at,
        )
        session.add(record)
        model.revision = (model.revision or 0) + 1
        await audit_service.append(session, action="model.capability_evidence_recorded", resource_type="model", resource_id=model_id, details={"actor": "local_system", "capability": capability, "provenance": provenance, "supported": values["supported"], "revision": model.revision})
        await session.commit()
        return record

    async def aggregate(self, session: AsyncSession, model_id: str, at: Optional[datetime] = None) -> Dict[str, Any]:
        if not await session.get(ModelRecord, model_id):
            raise DomainError("resource_not_found", message="Model was not found.")
        at = at or datetime.utcnow()
        rows = (await session.execute(
            select(ModelCapabilityEvidenceRecord)
            .where(ModelCapabilityEvidenceRecord.model_id == model_id)
            .order_by(ModelCapabilityEvidenceRecord.observed_at.desc())
        )).scalars().all()
        current = [row for row in rows if row.expires_at is None or row.expires_at > at]
        grouped: Dict[str, list[ModelCapabilityEvidenceRecord]] = {}
        for row in current:
            grouped.setdefault(row.capability, []).append(row)
        resolved = {}
        conflicts = []
        for capability, evidence in grouped.items():
            ordered = sorted(evidence, key=lambda row: (PRECEDENCE[row.provenance], row.observed_at), reverse=True)
            winner = ordered[0]
            disagreements = [row for row in ordered[1:] if row.supported != winner.supported]
            if disagreements:
                conflicts.append({"capability": capability, "winner": winner.id, "conflicting_evidence": [row.id for row in disagreements]})
            resolved[capability] = {
                "supported": winner.supported,
                "score": winner.score,
                "provenance": winner.provenance,
                "evidence_id": winner.id,
                "observed_at": winner.observed_at.isoformat(),
            }
        return {"model_id": model_id, "resolved": resolved, "conflicts": conflicts, "evidence_count": len(current)}

    async def list(self, session: AsyncSession, model_id: str) -> list[ModelCapabilityEvidenceRecord]:
        return (await session.execute(
            select(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id).order_by(ModelCapabilityEvidenceRecord.observed_at.desc())
        )).scalars().all()


capability_evidence_service = CapabilityEvidenceService()
