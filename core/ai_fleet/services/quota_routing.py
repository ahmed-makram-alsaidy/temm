from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..routing import RoutingCandidate
from .quota import QuotaService


class QuotaAwareRoutingService:
    def __init__(self, quota: QuotaService): self._quota = quota

    async def assess(self, session: AsyncSession, candidates: List[RoutingCandidate], required_units: Dict[str, float], at: datetime | None = None) -> Dict[str, Any]:
        eligible = []
        rejected = []
        evidence = {}
        for candidate in candidates:
            if not candidate.provider_instance_id:
                eligible.append(candidate)
                evidence[candidate.route_id] = {"state": "unknown", "reason": "provider_instance_unavailable"}
                continue
            observations = await self._quota.current(session, candidate.provider_instance_id, at)
            by_scope = {}
            for observation in observations:
                if observation.scope not in by_scope: by_scope[observation.scope] = observation
            blockers = []
            route_evidence = []
            for scope, required in required_units.items():
                observation = by_scope.get(scope)
                if not observation or observation.source == "unknown" or observation.remaining_value is None:
                    route_evidence.append({"scope": scope, "state": "unknown", "reason": "current_quota_unavailable"})
                    continue
                item = {"scope": scope, "state": "current", "remaining": observation.remaining_value, "required": required, "unit": observation.unit, "source": observation.source, "checked_at": observation.checked_at.isoformat(), "expires_at": observation.expires_at.isoformat(), "resets_at": observation.resets_at.isoformat() if observation.resets_at else None}
                route_evidence.append(item)
                if observation.remaining_value < required: blockers.append(f"quota_insufficient:{scope}")
            evidence[candidate.route_id] = route_evidence
            if blockers: rejected.append({"route_id": candidate.route_id, "blockers": blockers})
            else: eligible.append(candidate)
        return {"eligible": eligible, "rejected": rejected, "evidence": evidence}


quota_aware_routing_service = QuotaAwareRoutingService(QuotaService())
