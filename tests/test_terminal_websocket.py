import asyncio
import unittest
import uuid

import httpx
from fastapi.testclient import TestClient

from core.ai_fleet.engine.event_bus import task_event_bus
from core.ai_fleet.main import app, close_terminal_stream
from core.ai_fleet.storage.database import init_db


class TerminalWebSocketTests(unittest.TestCase):
    def test_terminal_socket_connects_accepts_commands_and_replays(self):
        task_id = f"websocket-terminal-{uuid.uuid4().hex}"
        # The journal is written before the app lifespan runs, so this test must
        # create the schema itself: relying on an earlier test to have done it
        # made the outcome depend on which files pytest was given.
        asyncio.run(init_db())
        published = asyncio.run(task_event_bus.publish(task_id, "terminal", text="replayed-output"))


        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/terminal/{task_id}") as socket:
                connected = socket.receive_json()
                replayed = socket.receive_json()
                self.assertEqual(connected["type"], "connected")
                self.assertIn("supported", connected["pty"])
                self.assertEqual(replayed["text"], "replayed-output")
                socket.send_json({"type": "ping"})
                self.assertEqual(socket.receive_json()["type"], "pong")
                socket.send_json({"type": "stdin", "data": "hello"})
                self.assertEqual(socket.receive_json()["type"], "command_error")
                socket.send_json({"type": "stdin", "data": "x" * 65537})
                self.assertIn("64 KiB", socket.receive_json()["message"])

            with client.websocket_connect(f"/ws/terminal/{task_id}?after={published['sequence']}") as socket:
                self.assertEqual(socket.receive_json()["type"], "connected")
                socket.send_json({"type": "ping"})
                self.assertEqual(socket.receive_json()["type"], "pong")


class TerminalStreamTeardownTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_teardown_reraises_the_callers_cancellation_and_still_releases(self):
        """A cancelled teardown must hand back the caller's own cancellation.

        A cancel scope absorbs only the cancellation it issued. Awaiting the
        children with gather substituted their bare cancellation for the caller's,
        so the scope refused to absorb it and every client that disconnected a
        moment before its handler finished closing was reported as a crashed
        handler - one run in four of this file's socket test.
        """
        released = []

        async def idle():
            # Cancelled without a handler of its own, so the cancellation it dies
            # of carries no message - exactly like send_events and
            # receive_commands, whose bare cancellation was the one substituted.
            await asyncio.Event().wait()

        sender = asyncio.create_task(idle())
        receiver = asyncio.create_task(idle())
        teardown = asyncio.create_task(close_terminal_stream(sender, receiver, lambda: released.append("released")))
        # One turn: long enough for the teardown to cancel both children and begin
        # awaiting them, short enough that neither has processed its cancellation.
        # That is the window a client disconnecting mid-close lands in, and the
        # only one in which the substitution happens.
        await asyncio.sleep(0)
        teardown.cancel("issued by the caller's scope")

        with self.assertRaises(asyncio.CancelledError) as caught:
            await teardown

        self.assertEqual(caught.exception.args, ("issued by the caller's scope",))
        self.assertEqual(released, ["released"])

    async def test_teardown_releases_the_subscription_on_the_ordinary_path(self):
        released = []

        async def waiting():
            await asyncio.Event().wait()

        sender = asyncio.create_task(waiting())
        receiver = asyncio.create_task(waiting())
        await close_terminal_stream(sender, receiver, lambda: released.append("released"))

        self.assertEqual(released, ["released"])
        self.assertTrue(sender.cancelled())
        self.assertTrue(receiver.cancelled())


class TerminalCapabilityApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_capability_api_reports_real_backend(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/terminal/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("supported", payload)
        self.assertIn("features", payload)
        if payload["supported"]:
            self.assertIn("stdin", payload["features"])
            self.assertIn("resize", payload["features"])


if __name__ == "__main__":
    unittest.main()
