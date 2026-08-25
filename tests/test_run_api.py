import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.engine.event_bus import task_event_bus
from core.ai_fleet.main import app
from core.ai_fleet.services.latency import LatencyService
from core.ai_fleet.services.run_artifacts import RunArtifactService
from core.ai_fleet.services.run_output import RunOutputService
from core.ai_fleet.services.usage import UsageService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import LatencyObservationRecord, RunArtifactRecord, RunAttemptRecord, RunOutputChunkRecord, TaskRun, UsageObservationRecord, WorkspaceRecord


class CanonicalRunApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.workspace_id = f"run-api-workspace-{id(self)}"
        self.run_id = f"run-api-detail-{id(self)}"
        self.attempt_id = f"run-api-attempt-{id(self)}"
        file = Path(self.folder.name) / "artifact.txt"
        file.write_text("artifact")
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Run API", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(TaskRun(id=self.run_id, prompt="run", workspace_id=self.workspace_id, status="completed", started_at=datetime.utcnow(), completed_at=datetime.utcnow()))
            session.add(RunAttemptRecord(id=self.attempt_id, run_id=self.run_id, attempt_number=1, executor_type="cli", status="completed", outcome="completed", receipt_json='{"exit_code":0}'))
            await session.commit()
            await RunOutputService().append(session, self.run_id, "stdout", "output", self.attempt_id)
            await RunArtifactService().register(session, self.run_id, "artifact.txt", "created", self.attempt_id)
            await UsageService().record(session, {"run_id": self.run_id, "input_tokens": 2, "source": "estimated", "method": "test"})
            await LatencyService().record(session, {"run_id": self.run_id, "duration_ms": 10, "source": "measured"})
            await session.commit()
        await task_event_bus.publish(self.run_id, "completed", reason="test")
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            for model in [RunArtifactRecord, RunOutputChunkRecord, UsageObservationRecord, LatencyObservationRecord, RunAttemptRecord]:
                await session.execute(delete(model).where(model.run_id == self.run_id))
            run = await session.get(TaskRun, self.run_id)
            if run: await session.delete(run)
            workspace = await session.get(WorkspaceRecord, self.workspace_id)
            if workspace: await session.delete(workspace)
            await session.commit()
        self.folder.cleanup()

    async def test_run_detail_subresources_and_pagination(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            listing = await client.get("/api/runs?limit=1")
            detail = await client.get(f"/api/runs/{self.run_id}")
            attempts = await client.get(f"/api/runs/{self.run_id}/attempts")
            events = await client.get(f"/api/runs/{self.run_id}/events")
            output = await client.get(f"/api/runs/{self.run_id}/output")
            artifacts = await client.get(f"/api/runs/{self.run_id}/artifacts")
            usage = await client.get(f"/api/runs/{self.run_id}/usage")
            latency = await client.get(f"/api/runs/{self.run_id}/latency")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.headers["x-result-count"], "1")
        self.assertEqual(detail.json()["id"], self.run_id)
        self.assertEqual(attempts.json()[0]["id"], self.attempt_id)
        self.assertTrue(events.json())
        self.assertEqual(output.json()[0]["content"], "output")
        self.assertEqual(artifacts.json()[0]["path"], "artifact.txt")
        self.assertEqual(usage.json()["usage"]["input_tokens"], 2)
        self.assertEqual(latency.json()["latency"]["duration_ms"], 10)

    async def test_missing_and_terminal_cancel(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            missing = await client.get("/api/runs/missing")
            cancelled = await client.post(f"/api/runs/{self.run_id}/cancel")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(cancelled.status_code, 409)


if __name__ == "__main__":
    unittest.main()
