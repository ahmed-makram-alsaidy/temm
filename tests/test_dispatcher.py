import asyncio
import unittest

from core.ai_fleet.services.dispatcher import DispatcherService


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrency_and_budget_are_bounded(self):
        active = 0
        maximum = 0
        async def dispatch(task_id):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {"status": "dispatched"}
        result = await DispatcherService().dispatch(["a", "b", "c"], dispatch, 2, "2.00", {"a": "0.50", "b": "0.50", "c": "2.00"}, {})
        self.assertEqual(result["launched"], ["a", "b"])
        self.assertEqual(result["skipped"], [{"task_id": "c", "reason": "budget_limit"}])
        self.assertLessEqual(maximum, 2)
        self.assertEqual(result["reserved_spend"], "1.00")

    async def test_pause_cancel_and_unknown_cost_stop_new_work(self):
        calls = []
        async def dispatch(task_id): calls.append(task_id); return {"status": "done"}
        paused = await DispatcherService().dispatch(["a"], dispatch, 1, "1", {"a": "0.1"}, {"paused": True})
        cancelled = await DispatcherService().dispatch(["a"], dispatch, 1, "1", {"a": "0.1"}, {"cancelled": True})
        unknown = await DispatcherService().dispatch(["a"], dispatch, 1, "1", {"a": None}, {})
        self.assertEqual(calls, [])
        self.assertEqual(paused["skipped"][0]["reason"], "orchestration_paused")
        self.assertEqual(cancelled["skipped"][0]["reason"], "orchestration_cancelled")
        self.assertEqual(unknown["skipped"][0]["reason"], "estimated_cost_unknown")


if __name__ == "__main__":
    unittest.main()
