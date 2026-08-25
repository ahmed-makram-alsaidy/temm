import unittest

from sqlalchemy import delete

from core.ai_fleet.services.runs import RunLifecycleService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import RunAttemptRecord, TaskRun


class RunLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"lifecycle-run-{id(self)}"
        self.service = RunLifecycleService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_id))
            run = await session.get(TaskRun, self.run_id)
            if run:
                await session.delete(run)
            await session.commit()

    async def test_run_attempt_and_idempotent_finalization(self):
        async with AsyncSessionLocal() as session:
            created = await self.service.create(session, run_id=self.run_id, prompt="test", routing_mode="balanced")
            self.assertEqual(created.status, "created")
            running = await self.service.start(session, self.run_id)
            attempt = await self.service.start_attempt(session, self.run_id, "cli", agent_id="agent")
            finalized_attempt = await self.service.finalize_attempt(session, attempt.id, status="completed", outcome="completed", receipt={"exit_code": 0})
            repeated_attempt = await self.service.finalize_attempt(session, attempt.id, status="completed", outcome="completed", receipt={"exit_code": 0})
            completed = await self.service.finalize(session, self.run_id, "completed")
            repeated = await self.service.finalize(session, self.run_id, "completed")
        self.assertEqual(running.status, "completed")
        self.assertEqual(finalized_attempt.id, repeated_attempt.id)
        self.assertEqual(completed.id, repeated.id)
        self.assertIsNotNone(completed.completed_at)

    async def test_invalid_transitions_and_conflicting_finalize_are_rejected(self):
        async with AsyncSessionLocal() as session:
            await self.service.create(session, run_id=self.run_id, prompt="test", routing_mode="balanced")
            with self.assertRaises(Exception):
                await self.service.finalize(session, self.run_id, "completed")
            await self.service.start(session, self.run_id)
            await self.service.finalize(session, self.run_id, "failed", "failure")
            with self.assertRaises(Exception):
                await self.service.finalize(session, self.run_id, "completed")

    async def test_startup_recovery_interrupts_only_nonterminal_runs_and_attempts(self):
        terminal_id = f"{self.run_id}-terminal"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_id, prompt="running", status="running", revision=1))
            session.add(RunAttemptRecord(id=f"{self.run_id}-attempt", run_id=self.run_id, attempt_number=1, executor_type="cli", status="running"))
            session.add(TaskRun(id=terminal_id, prompt="done", status="completed", revision=1))
            await session.commit()
            recovered = await self.service.recover_interrupted(session)
            again = await self.service.recover_interrupted(session)
            run = await session.get(TaskRun, self.run_id)
            attempt = await session.get(RunAttemptRecord, f"{self.run_id}-attempt")
            terminal = await session.get(TaskRun, terminal_id)
            self.assertEqual(recovered, [self.run_id])
            self.assertEqual(again, [])
            self.assertEqual(run.status, "interrupted")
            self.assertEqual(run.status_reason, "service_restart")
            self.assertEqual(attempt.status, "interrupted")
            self.assertEqual(attempt.to_dict()["receipt"]["error_code"], "service_restart")
            self.assertEqual(terminal.status, "completed")
            await session.delete(terminal)
            await session.commit()

    async def test_cancellation_request_is_idempotent(self):
        async with AsyncSessionLocal() as session:
            await self.service.create(session, run_id=self.run_id, prompt="test", routing_mode="balanced")
            await self.service.start(session, self.run_id)
            one = await self.service.request_cancel(session, self.run_id)
            two = await self.service.request_cancel(session, self.run_id)
            self.assertEqual(one.id, two.id)
            self.assertEqual(two.status, "cancellation_requested")
            await self.service.finalize(session, self.run_id, "cancelled")


if __name__ == "__main__":
    unittest.main()
