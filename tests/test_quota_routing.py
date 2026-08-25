import unittest
from datetime import datetime, timedelta

from sqlalchemy import delete

from core.ai_fleet.routing import RoutingCandidate, RoutingEvidence, unknown_evidence
from core.ai_fleet.services.quota_routing import QuotaAwareRoutingService
from core.ai_fleet.services.quota import QuotaService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProviderInstanceRecord, QuotaObservationRecord


class QuotaAwareRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.now = datetime.utcnow(); self.provider_ids = [f"quota-route-{id(self)}-{i}" for i in range(3)]
        async with AsyncSessionLocal() as session:
            for provider_id in self.provider_ids: session.add(ProviderInstanceRecord(id=provider_id, adapter_id="custom", name=provider_id, configuration="{}"))
            await session.commit()
            await QuotaService().record(session, self.provider_ids[0], {"scope": "requests", "unit": "requests", "limit": 100, "remaining": 0, "source": "provider_reported", "checked_at": self.now, "ttl_seconds": 300})
            stale = await QuotaService().record(session, self.provider_ids[1], {"scope": "requests", "unit": "requests", "limit": 100, "remaining": 0, "source": "provider_reported", "checked_at": self.now - timedelta(days=1), "ttl_seconds": 10})
            await QuotaService().record(session, self.provider_ids[2], {"scope": "requests", "unit": "requests", "remaining": None, "source": "unknown", "checked_at": self.now, "ttl_seconds": 300})
        self.service = QuotaAwareRoutingService(QuotaService())

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.provider_instance_id.in_(self.provider_ids)))
            await session.execute(delete(ProviderInstanceRecord).where(ProviderInstanceRecord.id.in_(self.provider_ids)))
            await session.commit()

    def candidate(self, index):
        return RoutingCandidate(f"route-{index}", None, f"model-{index}", self.provider_ids[index], {"coding": RoutingEvidence(True, "measured")}, RoutingEvidence(True, "measured"), unknown_evidence("none"), unknown_evidence("none"), unknown_evidence("none"), unknown_evidence("none"), RoutingEvidence(1000, "provider_reported"), True)

    async def test_only_current_explicit_insufficiency_rejects_route(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.assess(session, [self.candidate(0), self.candidate(1), self.candidate(2)], {"requests": 1}, self.now)
        self.assertEqual([item.route_id for item in result["eligible"]], ["route-1", "route-2"])
        self.assertEqual(result["rejected"][0]["blockers"], ["quota_insufficient:requests"])
        self.assertEqual(result["evidence"]["route-1"][0]["state"], "unknown")
        self.assertEqual(result["evidence"]["route-2"][0]["state"], "unknown")


if __name__ == "__main__": unittest.main()
