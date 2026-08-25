import json
import unittest

from sqlalchemy import delete, select

from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import RunAttemptRecord, TaskRun


class CanonicalRunSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"canonical-run-{id(self)}"

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_id))
            run = await session.get(TaskRun, self.run_id)
            if run:
                await session.delete(run)
            await session.commit()

    async def test_attempts_preserve_independent_receipts_and_outcomes(self):
        async with AsyncSessionLocal() as session:
            run = TaskRun(id=self.run_id, prompt="test", status="running", revision=1)
            first = RunAttemptRecord(id=f"{self.run_id}-1", run_id=self.run_id, attempt_number=1, executor_type="provider", status="failed", outcome="non_zero_exit", error_code="rate_limited", receipt_json=json.dumps({"exit_code": 1}))
            second = RunAttemptRecord(id=f"{self.run_id}-2", run_id=self.run_id, attempt_number=2, executor_type="cli", status="completed", outcome="completed", receipt_json=json.dumps({"exit_code": 0}))
            run.current_attempt_id = second.id
            session.add_all([run, first, second])
            await session.commit()
            attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_id).order_by(RunAttemptRecord.attempt_number))).scalars().all()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].error_code, "rate_limited")
        self.assertEqual(attempts[0].to_dict()["receipt"]["exit_code"], 1)
        self.assertEqual(attempts[1].to_dict()["receipt"]["exit_code"], 0)
        self.assertEqual(run.current_attempt_id, second.id)

    async def test_run_serialization_exposes_canonical_lifecycle_fields(self):
        run = TaskRun(id=self.run_id, prompt="test", project_id="project-1", workflow_id="workflow-1", status_reason="waiting", revision=2)
        payload = run.to_dict()
        self.assertEqual(payload["project_id"], "project-1")
        self.assertEqual(payload["workflow_id"], "workflow-1")
        self.assertEqual(payload["status_reason"], "waiting")
        self.assertEqual(payload["revision"], 2)
        self.assertIsNone(payload["actual_cost"])
        self.assertEqual(payload["financials"], {})


if __name__ == "__main__":
    unittest.main()
