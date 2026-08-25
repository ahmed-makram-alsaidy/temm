import unittest
from datetime import datetime

from sqlalchemy import delete

from core.ai_fleet.services.latency import LatencyService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import LatencyObservationRecord


class LatencyObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"latency-run-{id(self)}"
        self.service = LatencyService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.run_id == self.run_id))
            await session.commit()

    async def test_measured_dimensions_and_unknowns_are_preserved(self):
        async with AsyncSessionLocal() as session:
            await self.service.record(session, {"run_id": self.run_id, "ttft_ms": 120, "duration_ms": 900, "source": "measured", "method": "wall_clock", "observed_at": datetime.utcnow()})
            await session.commit()
            aggregate = await self.service.aggregate(session, self.run_id)
        self.assertEqual(aggregate["latency"]["ttft_ms"], 120)
        self.assertEqual(aggregate["provenance"]["duration_ms"], "measured")
        self.assertIsNone(aggregate["latency"]["queue_ms"])
        self.assertEqual(aggregate["provenance"]["queue_ms"], "unknown")
        self.assertIsNone(aggregate["latency"]["tokens_per_second"])

    async def test_invalid_latency_is_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception):
                await self.service.record(session, {"run_id": self.run_id, "duration_ms": -1, "source": "measured"})
            with self.assertRaises(Exception):
                await self.service.record(session, {"run_id": self.run_id, "duration_ms": 1, "source": "estimated"})


if __name__ == "__main__":
    unittest.main()
