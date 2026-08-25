import asyncio
import sys
import unittest

import httpx
import psutil

from core.ai_fleet.engine.process_manager import process_manager
from core.ai_fleet.main import app


class ExecutionApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await process_manager.shutdown()

    async def test_cancel_managed_execution_and_read_final_receipt(self):
        task_id = "api-cancel-test"
        execution = asyncio.create_task(
            process_manager.execute_argv(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                task_id=task_id,
                timeout_seconds=30,
            )
        )
        await self._wait_until_running(task_id)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "cancellation_requested")
            result = await execution
            response = await client.get(f"/api/tasks/{task_id}/execution")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["active"])
        self.assertEqual(payload["state"], "cancelled")
        self.assertEqual(payload["receipt"]["outcome"], "cancelled")
        self.assertFalse(psutil.pid_exists(result["pid"]))

    async def test_cancel_unknown_execution_returns_not_found(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/tasks/not-active/cancel")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "active_execution_not_found")

    async def _wait_until_running(self, task_id):
        for _ in range(100):
            if process_manager.get_state(task_id) == "running":
                return
            await asyncio.sleep(0.01)
        self.fail(f"{task_id} did not start")


if __name__ == "__main__":
    unittest.main()
