import unittest

from sqlalchemy import delete

from core.ai_fleet.engine.event_bus import TaskEventBus
from core.ai_fleet.services.event_journal import EventJournal
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import EventJournalRecord


class EventJournalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(EventJournalRecord).where(EventJournalRecord.correlation_id.in_(self.ids)))
                await session.commit()

    async def test_replay_survives_new_bus_instance_and_uses_cursor(self):
        correlation = f"journal-restart-{id(self)}"
        self.ids.append(correlation)
        first_bus = TaskEventBus()
        one = await first_bus.publish(correlation, "started", value=1)
        two = await first_bus.publish(correlation, "output", value=2)
        second_bus = TaskEventBus()
        queue = await second_bus.subscribe_persistent(correlation, after_sequence=one["sequence"])
        replayed = await queue.get()
        self.assertEqual(replayed["event_id"], two["event_id"])
        self.assertEqual(replayed["sequence"], two["sequence"])
        self.assertTrue(two["sequence"] > one["sequence"])

    async def test_retention_is_bounded_per_correlation(self):
        correlation = f"journal-retention-{id(self)}"
        self.ids.append(correlation)
        journal = EventJournal(retention_per_correlation=3)
        from core.ai_fleet.events import DomainEvent

        for index in range(5):
            event = DomainEvent.create("task.output", correlation, {"index": index}).to_dict()
            await journal.append(event)
        replay = await journal.replay(correlation)
        self.assertEqual(len(replay), 3)
        self.assertEqual([item["payload"]["index"] for item in replay], [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
