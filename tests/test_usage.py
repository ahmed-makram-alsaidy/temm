import unittest
from datetime import datetime, timedelta

from sqlalchemy import delete

from core.ai_fleet.services.usage import UsageService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import UsageObservationRecord


class UsageObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"usage-run-{id(self)}"
        self.service = UsageService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.run_id == self.run_id))
            await session.commit()

    async def test_provider_usage_wins_dimension_without_deleting_estimate(self):
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            await self.service.record(session, {"run_id": self.run_id, "input_tokens": 100, "output_tokens": 50, "source": "estimated", "method": "word_count", "observed_at": now})
            await self.service.record(session, {"run_id": self.run_id, "output_tokens": 42, "cached_tokens": 5, "source": "provider_reported", "observed_at": now + timedelta(seconds=1)})
            await session.commit()
            aggregate = await self.service.aggregate(session, self.run_id)
        self.assertEqual(aggregate["usage"]["input_tokens"], 100)
        self.assertEqual(aggregate["provenance"]["input_tokens"], "estimated")
        self.assertEqual(aggregate["usage"]["output_tokens"], 42)
        self.assertEqual(aggregate["provenance"]["output_tokens"], "provider_reported")
        self.assertEqual(len(aggregate["observations"]), 2)

    async def test_invalid_usage_is_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception):
                await self.service.record(session, {"run_id": self.run_id, "input_tokens": -1, "source": "measured"})
            with self.assertRaises(Exception):
                await self.service.record(session, {"run_id": self.run_id, "input_tokens": 1, "source": "estimated"})


if __name__ == "__main__":
    unittest.main()
