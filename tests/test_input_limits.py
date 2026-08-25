import json
import unittest

import httpx
from fastapi.testclient import TestClient

from core.ai_fleet.main import app


class InputLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = httpx.ASGITransport(app=app)

    async def test_http_body_over_two_mib_is_rejected(self):
        body = json.dumps({"prompt": "x" * (2 * 1024 * 1024), "routing_mode": "balanced"})
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post("/api/tasks/preflight", content=body, headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"]["code"], "request_too_large")

    async def test_prompt_command_and_path_limits(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            prompt = await client.post("/api/tasks/preflight", json={"prompt": "x" * 262145})
            command = await client.post("/api/terminal/run", json={"command": "x" * 262145})
            path = await client.post("/api/plugins/inspect", json={"folder_path": "x" * 1025})
        self.assertEqual(prompt.status_code, 422)
        self.assertEqual(command.status_code, 422)
        self.assertEqual(path.status_code, 422)

    async def test_extra_fields_and_oversized_lists_are_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            extra = await client.post("/api/tasks/preflight", json={"prompt": "ok", "unexpected": True})
            shells = await client.post("/api/workspaces", json={"name": "x", "path": "C:\\", "allowed_shells": ["cmd"] * 5})
        self.assertEqual(extra.status_code, 422)
        self.assertEqual(shells.status_code, 422)


class WebSocketInputLimitTests(unittest.TestCase):
    def test_malformed_and_oversized_messages_are_rejected_without_disconnect(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/terminal/input-limit") as socket:
                socket.receive_json()
                socket.send_text("not-json")
                malformed = socket.receive_json()
                socket.send_text(json.dumps({"type": "stdin", "data": "x" * 65536}))
                oversized = socket.receive_json()
        self.assertEqual(malformed["type"], "command_error")
        self.assertIn("Malformed", malformed["message"])
        self.assertEqual(oversized["type"], "command_error")
        self.assertIn("64 KiB", oversized["message"])


if __name__ == "__main__":
    unittest.main()
