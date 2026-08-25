import json
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import LatencyObservationRecord


DIMENSIONS = ["queue_ms", "launch_ms", "ttft_ms", "duration_ms", "tokens_per_second"]
SOURCES = {"measured", "provider_reported", "estimated", "unknown"}


class LatencyService:
    async def record(self, session: AsyncSession, values: Dict[str, Any]) -> LatencyObservationRecord:
        source = values["source"]
        if source not in SOURCES:
            raise DomainError("validation_failed", message="Latency source is invalid.")
        dimensions = {key: values.get(key) for key in DIMENSIONS}
        if all(value is None for value in dimensions.values()) or any(value is not None and value < 0 for value in dimensions.values()):
            raise DomainError("validation_failed", message="Latency dimensions must be non-negative and at least one is required.")
        if source == "estimated" and not values.get("method"):
            raise DomainError("validation_failed", message="Estimated latency requires a method.")
        record = LatencyObservationRecord(
            id=f"latency-{uuid.uuid4().hex[:12]}", run_id=values["run_id"], attempt_id=values.get("attempt_id"),
            source=source, method=values.get("method"), metadata_json=json.dumps(values.get("metadata", {})),
            observed_at=values.get("observed_at") or datetime.utcnow(), **dimensions,
        )
        session.add(record)
        await session.flush()
        return record

    async def aggregate(self, session: AsyncSession, run_id: str) -> Dict[str, Any]:
        rows = (await session.execute(select(LatencyObservationRecord).where(LatencyObservationRecord.run_id == run_id).order_by(LatencyObservationRecord.observed_at.desc()))).scalars().all()
        resolved = {}
        provenance = {}
        for dimension in DIMENSIONS:
            candidate = next((row for row in rows if getattr(row, dimension) is not None), None)
            resolved[dimension] = getattr(candidate, dimension) if candidate else None
            provenance[dimension] = candidate.source if candidate else "unknown"
        return {"run_id": run_id, "latency": resolved, "provenance": provenance, "observations": [row.to_dict() for row in rows]}


latency_service = LatencyService()
