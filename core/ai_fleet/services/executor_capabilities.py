from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .capability_evidence import CapabilityEvidenceService


class ExecutorCapabilityService:
    def __init__(self):
        self.evidence = CapabilityEvidenceService()

    async def observe(self, session: AsyncSession, model_id: str, capability: str, supported: bool, evidence: dict[str, Any], ttl_seconds: int = 3600) -> dict:
        now = datetime.utcnow()
        record = await self.evidence.record(session, model_id, {
            "capability": capability,
            "supported": supported,
            "score": 100 if supported else None,
            "provenance": "execution_measured",
            "source_type": "execution",
            "source_uri": evidence.get("run_id", ""),
            "evidence": evidence,
            "observed_at": now,
            "expires_at": now + timedelta(seconds=ttl_seconds),
        })
        return record.to_dict()

    async def certify(self, session: AsyncSession, model_id: str, observations: dict[str, bool], evidence: dict[str, Any], ttl_seconds: int = 3600) -> dict:
        records = {}
        for capability, supported in observations.items():
            records[capability] = await self.observe(session, model_id, capability, supported, evidence, ttl_seconds)
        return records

    async def satisfies(self, session: AsyncSession, model_id: str, required: set[str]) -> tuple[bool, dict]:
        aggregate = await self.evidence.aggregate(session, model_id)
        resolved = aggregate["resolved"]
        missing = sorted(item for item in required if not resolved.get(item, {}).get("supported"))
        return not missing, {"resolved": resolved, "missing": missing}


executor_capability_service = ExecutorCapabilityService()
