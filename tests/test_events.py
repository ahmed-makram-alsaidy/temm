import asyncio
import unittest

from core.ai_fleet.engine.event_bus import TaskEventBus
from core.ai_fleet.events import DomainEvent, EVENT_SCHEMA_VERSION


class DomainEventTests(unittest.TestCase):
    def test_event_is_versioned_and_correlated(self):
        event = DomainEvent.create("task.started", "task-1", {"agent_id": "agent-1"}, "evt-cause")
        payload = event.to_dict()
        self.assertEqual(payload["schema_version"], EVENT_SCHEMA_VERSION)
        self.assertTrue(payload["event_id"].startswith("evt-"))
        self.assertEqual(payload["correlation_id"], "task-1")
        self.assertEqual(payload["causation_id"], "evt-cause")

    def test_invalid_names_ids_and_oversized_payloads_are_rejected(self):
        with self.assertRaises(ValueError):
            DomainEvent.create("Bad Event", "task-1", {})
        with self.assertRaises(ValueError):
            DomainEvent.create("task.started", "bad id", {})
        with self.assertRaises(ValueError):
            DomainEvent.create("task.output", "task-1", {"text": "x" * (256 * 1024)})


class TypedTaskEventBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_bus_preserves_legacy_fields_and_adds_typed_contract(self):
        bus = TaskEventBus()
        queue = bus.subscribe("task-typed")
        event = await bus.publish("task-typed", "started", message="running")
        received = await asyncio.wait_for(queue.get(), 1)
        self.assertEqual(received, event)
        self.assertEqual(event["type"], "started")
        self.assertEqual(event["event_type"], "task.started")
        self.assertEqual(event["task_id"], "task-typed")
        self.assertEqual(event["payload"], {"message": "running"})
        self.assertEqual(event["message"], "running")

    async def test_history_is_bounded(self):
        bus = TaskEventBus()
        for index in range(130):
            await bus.publish("task-history", "output", text=str(index))
        self.assertEqual(len(bus._history["task-history"]), 120)
        self.assertEqual(bus._history["task-history"][0]["text"], "10")


if __name__ == "__main__":
    unittest.main()
