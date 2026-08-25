import asyncio
import sys
import unittest

from core.ai_fleet.engine.event_bus import TaskEventBus
from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.security import REDACTED, SensitiveDataRedactor
from core.ai_fleet.storage.secret_vault import secret_vault


class SensitiveDataRedactorTests(unittest.TestCase):
    def test_recursive_and_pattern_redaction(self):
        redactor = SensitiveDataRedactor(["known-secret-123456"])
        value = {
            "message": "known-secret-123456 Bearer abcdefghijklmnop",
            "password": "anything",
            "nested": ["sk-test_abcdefghijklmnop"],
        }
        redacted = redactor.redact(value)
        self.assertNotIn("known-secret", str(redacted))
        self.assertEqual(redacted["password"], REDACTED)
        self.assertIn(REDACTED, redacted["message"])
        self.assertEqual(redacted["nested"], [REDACTED])


class SecurityEgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = "test-redaction-secret"
        self.secret = "agent-ultra-secret-739204857"
        secret_vault.set_key(self.key, self.secret)

    async def asyncTearDown(self):
        secret_vault.delete_key(self.key)

    async def test_process_receipt_and_chunks_are_redacted(self):
        manager = ProcessManager()
        chunks = []
        result = await manager.execute_argv(
            [sys.executable, "-c", f"import sys;print({self.secret!r});print({self.secret!r},file=sys.stderr)"],
            task_id="redaction-process",
            timeout_seconds=5,
            on_chunk=lambda text, stream: chunks.append((stream, text)),
        )
        combined = result["stdout"] + result["stderr"] + str(chunks)
        self.assertNotIn(self.secret, combined)
        self.assertIn(REDACTED, combined)
        await manager.shutdown()

    async def test_event_payload_history_and_queue_are_redacted(self):
        bus = TaskEventBus()
        queue = bus.subscribe("redaction-event")
        await bus.publish(
            "redaction-event",
            "output",
            text=f"value={self.secret}",
            nested={"token": self.secret, "safe": "visible"},
        )
        event = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertNotIn(self.secret, str(event))
        self.assertEqual(event["nested"]["token"], REDACTED)
        replay = bus.subscribe("redaction-event")
        replayed = await asyncio.wait_for(replay.get(), timeout=1)
        self.assertNotIn(self.secret, str(replayed))


if __name__ == "__main__":
    unittest.main()
