import unittest
import unittest.mock

import httpx

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import init_db


class HealthApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)

    async def test_reserved_backend_paths_never_fall_through_to_spa(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")

    async def test_liveness_is_minimal(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/fleet/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})

    async def test_readiness_reports_database_frontend_and_execution_evidence(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/fleet/health/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["database"]["ready"])
        self.assertEqual(payload["database"]["integrity"], "ok")
        self.assertEqual(payload["database"]["migrations"], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41])
        self.assertIn("verified_agents", payload["execution"])
        self.assertIn("pty", payload["execution"])
        self.assertIn("host", payload["execution"])
        self.assertIsInstance(payload["frontend"]["ready"], bool)

    async def test_readiness_calls_a_host_with_no_room_degraded_while_still_serving(self):
        """During the memory incident of 2026-08-21 this endpoint reported `ready` with
        nothing wrong, while every dispatch aborted before its first model step. The
        status stays `ready` deliberately - the API is serving, and a shortage passes -
        but execution capacity is not, which is what `degraded` reports."""
        exhausted = {
            "measurable": True, "sufficient": False, "pressure": True,
            "reason": "host_memory_and_pagefile_exhausted",
            "detail": "0.01 GB of combined memory and page file remains.",
        }
        with unittest.mock.patch("core.ai_fleet.api.routes.host_capacity", return_value=exhausted):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.get("/api/fleet/health/ready")
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["execution"]["degraded"])
        self.assertEqual(payload["execution"]["host"]["reason"], "host_memory_and_pagefile_exhausted")


if __name__ == "__main__":
    unittest.main()
