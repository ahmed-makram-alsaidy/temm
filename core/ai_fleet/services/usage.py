import json
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import UsageObservationRecord


SOURCES = {"measured", "provider_reported", "estimated", "unknown"}
PRECEDENCE = {"provider_reported": 3, "measured": 2, "estimated": 1, "unknown": 0}
DIMENSIONS = ["requests", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]


class UsageService:
    async def record(self, session: AsyncSession, values: Dict[str, Any]) -> UsageObservationRecord:
        source = values["source"]
        if source not in SOURCES:
            raise DomainError("validation_failed", message="Usage source is invalid.")
        if source == "estimated" and not values.get("method"):
            raise DomainError("validation_failed", message="Estimated usage requires a method.")
        dimensions = {key: values.get(key) for key in DIMENSIONS}
        if all(value is None for value in dimensions.values()) or any(value is not None and value < 0 for value in dimensions.values()):
            raise DomainError("validation_failed", message="Usage dimensions must be non-negative and at least one is required.")
        record = UsageObservationRecord(
            id=f"usage-{uuid.uuid4().hex[:12]}",
            run_id=values["run_id"], attempt_id=values.get("attempt_id"),
            model_id=values.get("model_id"), provider_instance_id=values.get("provider_instance_id"),
            source=source, method=values.get("method"), metadata_json=json.dumps(values.get("metadata", {})),
            observed_at=values.get("observed_at") or datetime.utcnow(), **dimensions,
        )
        session.add(record)
        await session.flush()
        return record

    async def aggregate(self, session: AsyncSession, run_id: str) -> Dict[str, Any]:
        rows = (await session.execute(select(UsageObservationRecord).where(UsageObservationRecord.run_id == run_id))).scalars().all()
        resolved = {}
        provenance = {}
        for dimension in DIMENSIONS:
            candidates = [row for row in rows if getattr(row, dimension) is not None]
            if candidates:
                winner = max(candidates, key=lambda row: (PRECEDENCE[row.source], row.observed_at))
                resolved[dimension] = getattr(winner, dimension)
                provenance[dimension] = winner.source
            else:
                resolved[dimension] = None
                provenance[dimension] = "unknown"
        return {"run_id": run_id, "usage": resolved, "provenance": provenance, "observations": [row.to_dict() for row in rows]}


usage_service = UsageService()
