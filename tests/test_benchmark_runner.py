import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.services.benchmark_suites import BenchmarkSuiteService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, AuditRecord, BenchmarkCaseRecord, BenchmarkSuiteVersionRecord, LatencyObservationRecord, RunAttemptRecord, RunOutputChunkRecord, TaskRun, WorkspaceRecord


class RealBenchmarkRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.workspace_id = f"benchmark-workspace-{id(self)}"
        self.agent_id = f"benchmark-agent-{id(self)}"
        self.suite_key = f"runner-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Benchmark", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(AgentRecord(id=self.agent_id, name="Python benchmark", cli_command=sys.executable, detected_path=sys.executable, discovery_source="manual", discovery_state="verified", status="ready", user_enabled=True, lifecycle_status="active", auth_state="not_required", permission_profile="developer", input_method="argument", supports_interactive=False, invocation_args=json.dumps(["-c", "import sys; print(sys.argv[1])", "{prompt}"])))
            await session.commit()
            self.version = await BenchmarkSuiteService().create_version(session, {"suite_key": self.suite_key, "name": "Runner", "category": "coding", "provenance": "user_authored", "cases": [{"case_key": "echo", "prompt": "REAL-BENCHMARK", "expected_behavior": "Echo input", "evaluator_type": "exact", "weight": 1}]})
        self.transport = httpx.ASGITransport(app=app)
        self.run_ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.run_ids:
                await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.run_id.in_(self.run_ids)))
                await session.execute(delete(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id.in_(self.run_ids)))
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(self.run_ids)))
                await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            await session.execute(delete(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id == self.version.id))
            await session.execute(delete(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.id == self.version.id))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.suite_key))
            await session.execute(delete(AgentRecord).where(AgentRecord.id == self.agent_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()

    async def test_real_case_creates_run_attempt_output_and_measured_rule_score(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post("/api/benchmarks/run-real", json={"suite_version_id": self.version.id, "agent_id": self.agent_id, "workspace_id": self.workspace_id, "timeout_seconds": 10})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["scores_computed"])
        self.assertEqual(payload["cases"][0]["score"], 0.0)
        self.assertEqual(payload["cases"][0]["score_provenance"], "measured")
        self.run_ids = [payload["cases"][0]["run_id"]]
        async with AsyncSessionLocal() as session:
            attempt = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == self.run_ids[0]))).scalar_one()
            output = (await session.execute(select(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id == self.run_ids[0]))).scalars().all()
            run = await session.get(TaskRun, self.run_ids[0])
        self.assertEqual(attempt.status, "completed")
        self.assertEqual(attempt.to_dict()["receipt"]["suite_version_id"], self.version.id)
        self.assertIn("REAL-BENCHMARK", "".join(item.content for item in output))
        self.assertEqual(json.loads(run.measurement_metadata)["evaluation"]["provenance"], "measured")
        self.assertEqual(run.quality_eval_score, 0.0)

    async def test_unready_agent_is_rejected(self):
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.user_enabled = False
            await session.commit()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post("/api/benchmarks/run-real", json={"suite_version_id": self.version.id, "agent_id": self.agent_id, "workspace_id": self.workspace_id})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
