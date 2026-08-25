import unittest

from sqlalchemy import delete, select

from core.ai_fleet.services.fallback import FallbackService
from core.ai_fleet.services.runs import RunLifecycleService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import RunAttemptRecord, TaskRun


class FallbackFailureMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.run_ids = []; self.lifecycle = RunLifecycleService(); self.service = FallbackService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.run_ids:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(self.run_ids)))
                await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
                await session.commit()

    async def running(self, suffix):
        run_id = f"fallback-{id(self)}-{suffix}"; self.run_ids.append(run_id)
        async with AsyncSessionLocal() as session:
            await self.lifecycle.create(session, run_id=run_id, prompt="x", routing_mode="balanced")
            await self.lifecycle.start(session, run_id)
        return run_id

    def routes(self): return [{"route_id": "one", "executable": True, "executor_type": "provider", "model_id": "m1"}, {"route_id": "two", "executable": True, "executor_type": "cli", "agent_id": "a2"}]

    async def test_retryable_failure_falls_back_and_persists_attempts(self):
        run_id = await self.running("retry")
        async def executor(route, attempt): return {"success": route["route_id"] == "two", "outcome": "completed" if route["route_id"] == "two" else "failed", "error_code": None if route["route_id"] == "two" else "rate_limited"}
        async with AsyncSessionLocal() as session:
            result = await self.service.execute(session, run_id, self.routes(), executor)
            attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id).order_by(RunAttemptRecord.attempt_number))).scalars().all()
        self.assertEqual(result["selected_route_id"], "two")
        self.assertEqual([attempt.error_code for attempt in attempts], ["rate_limited", None])
        self.assertEqual(attempts[0].to_dict()["receipt"]["fallback_index"], 0)

    async def test_nonretryable_failure_stops_chain(self):
        run_id = await self.running("terminal"); calls = []
        async def executor(route, attempt): calls.append(route["route_id"]); return {"success": False, "outcome": "failed", "error_code": "auth_failed"}
        async with AsyncSessionLocal() as session: result = await self.service.execute(session, run_id, self.routes(), executor)
        self.assertEqual(calls, ["one"]); self.assertEqual(result["status"], "failed")

    async def test_cancellation_halts_chain(self):
        run_id = await self.running("cancel")
        async def executor(route, attempt): return {"success": False, "outcome": "cancelled", "error_code": "cancelled"}
        async with AsyncSessionLocal() as session: result = await self.service.execute(session, run_id, self.routes(), executor)
        self.assertEqual(result["status"], "cancelled"); self.assertEqual(len(result["attempts"]), 1)


if __name__ == "__main__": unittest.main()
