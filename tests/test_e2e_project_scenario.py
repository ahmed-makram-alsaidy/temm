"""End-to-end project scenario: exercises the real TEMM production chain."""
import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.services.executor_capabilities import ExecutorCapabilityService
from core.ai_fleet.storage.models import (
    AgentRecord, BlueprintProposalRecord, ContextPackRecord, DeliverableRecord,
    ModelCapabilityEvidenceRecord, ModelRecord, OrchestrationCheckpointRecord,
    OrchestrationTaskRecord, ProjectRecord, ProjectRequirementRecord, RunAttemptRecord,
    RunOutputChunkRecord, TaskRun, WorkspaceRecord,
)


class EndToEndProjectScenarioTests(unittest.IsolatedAsyncioTestCase):
    """Proves the real production chain from project goal to deliverable package."""

    async def asyncSetUp(self):
        await init_db()
        self.suffix = uuid.uuid4().hex[:8]
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        # Create a minimal project workspace with a package.json for engineering gate
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "echo PASS"}}))
        (self.root / "index.html").write_text("<html><body>Hello World</body></html>")
        self.transport = httpx.ASGITransport(app=app)
        # Seed agent fixture
        self.agent_id = f"e2e-agent-{self.suffix}"
        self.workspace_id = f"e2e-workspace-{self.suffix}"
        self.model_id = f"e2e/{self.suffix}-route"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="E2E", path=str(self.root), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(AgentRecord(id=self.agent_id, name="E2E Agent", cli_command=sys.executable, detected_path=sys.executable, capabilities='["coding"]', invocation_args=json.dumps(["-c", "open('homepage.html', 'w', encoding='utf-8').write('<html><body><h1>Hero</h1></body></html>'); print('website-built')"]), input_method="argument", output_method="stdout", working_directory="workspace", tool_kind="agent", user_enabled=True, lifecycle_status="active", discovery_state="verified", status="ready", auth_state="not_required", permission_profile="developer", discovery_source="manual"))
            # Route selection only considers discovered external-tool models with
            # unexpired availability, so the fixture has to supply one. Without it
            # this test dispatched successfully only because it was reading the
            # operator's own TEMM database, and it began failing `execution_unavailable`
            # the moment pytest was pointed at an isolated store - a dependency on
            # production state, not a real assertion about the chain.
            now = datetime.utcnow()
            session.add(ModelRecord(
                id=self.model_id, name="E2E Route", provider=self.suffix, category="balanced",
                source_type="external_tool", source_uri="opencode-cli", lifecycle_status="active",
                is_active=True, availability_state="available", availability_checked_at=now,
                availability_expires_at=now + timedelta(hours=1),
                availability_evidence=json.dumps({"source": "e2e_fixture"}),
            ))
            await session.commit()
            await ExecutorCapabilityService().certify(
                session, self.model_id,
                {"coding": True, "file_read": True, "file_write": True, "text_generation": True},
                {"source": "e2e_fixture"},
            )
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            # Clean up in dependency order
            project_ids = [r.id for r in (await session.execute(select(ProjectRecord).where(ProjectRecord.slug.like(f"e2e-{self.suffix}%")))).scalars().all()]
            if project_ids:
                runs = (await session.execute(select(TaskRun.id).where(TaskRun.project_id.in_(project_ids)))).scalars().all()
                if runs:
                    await session.execute(delete(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id.in_(runs)))
                    await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(runs)))
                    await session.execute(delete(ContextPackRecord).where(ContextPackRecord.run_id.in_(runs)))
                    await session.execute(delete(TaskRun).where(TaskRun.id.in_(runs)))
                await session.execute(delete(DeliverableRecord).where(DeliverableRecord.project_id.in_(project_ids)))
                await session.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.project_id.in_(project_ids)))
                await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id.in_(project_ids)))
                await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id.in_(project_ids)))
                await session.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.project_id.in_(project_ids)))
                await session.execute(delete(ProjectRecord).where(ProjectRecord.id.in_(project_ids)))
            await session.execute(delete(AgentRecord).where(AgentRecord.id == self.agent_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == self.model_id))
            await session.commit()
        self.temp.cleanup()

    async def test_full_project_chain_from_goal_to_deliverable(self):
        """
        USER GOAL → PROJECT → REQUIREMENTS → TASK GRAPH → DISPATCH → EXECUTION
        → QUALITY GATES → COMPLETION ASSESSMENT → DELIVERABLE PACKAGE
        """
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            # 1. Create Project
            project = (await client.post("/api/projects", json={"name": "Company Website", "slug": f"e2e-{self.suffix}", "purpose": "Build a complete professional company website", "project_type": "website"})).json()
            self.assertEqual(project["project_type"], "website")
            project_id = project["id"]

            # 2. Create Requirement (simulating approved blueprint output)
            requirement = (await client.post(f"/api/projects/{project_id}/requirements", json={"title": "Build homepage", "description": "Create a responsive homepage with hero section", "requirement_type": "functional", "source_type": "user", "truth_state": "confirmed", "priority": "must", "acceptance": [{"statement": "Homepage renders correctly"}]})).json()
            requirement_id = requirement["id"]

            # 3. Approve requirement
            await client.post(f"/api/projects/requirements/{requirement_id}/transition", json={"target": "approved"})

            # 4. Create orchestration checkpoint
            checkpoint = (await client.post("/api/orchestrations", json={"project_id": project_id})).json()
            checkpoint_id = checkpoint["id"]

            # 5. Advance to approved state
            await client.post(f"/api/orchestrations/{checkpoint_id}/analyze", json={"payload": {"goal": "Build website"}})
            await client.post(f"/api/orchestrations/{checkpoint_id}/plan", json={"payload": {}})
            await client.post(f"/api/orchestrations/{checkpoint_id}/approve", json={"payload": {}})

            # 6. Create orchestration task linked to requirement
            async with AsyncSessionLocal() as session:
                from core.ai_fleet.services.orchestration_tasks import OrchestrationTaskService
                task = await OrchestrationTaskService().create(session, project_id, {
                    "task_type": "implementation",
                    "title": "Build homepage",
                    "description": "Create responsive homepage with hero",
                    "requirement_ids": [requirement_id],
                    # A machine-checkable criterion, so the chain proves completion on
                    # the artifact the executor actually produced. A prose criterion
                    # can never be satisfied, which left this step asserting only that
                    # the dispatch failed in the expected way.
                    "acceptance": [{"criterion_id": "homepage", "description": "Homepage file exists", "evaluator": {"type": "path_exists_contains", "path": "homepage.html", "contains": ["Hero"]}}],
                    "context_refs": [{"source_type": "requirement", "source_id": requirement_id}],
                    "executor_needs": {"capabilities": ["coding"]},
                })
                task_id = task.id

            # 7. Dispatch (real execution)
            dispatch = (await client.post(f"/api/orchestrations/{checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "token_limit": 32000, "timeout_seconds": 30})).json()
            self.assertEqual(dispatch["status"], "running")
            self.assertEqual(len(dispatch["dispatched"]), 1)
            dispatched = dispatch["dispatched"][0]
            self.assertEqual(dispatched["status"], "completed")
            self.assertTrue(dispatched["task_completion_claimed"])
            self.assertTrue(dispatched["all_acceptance_satisfied"])

            # 8. Verify quality gates were executed
            self.assertIn("quality_findings", dispatched)
            # The workspace has package.json with "test" script, so engineering gate ran
            self.assertTrue(len(dispatched["quality_findings"]) >= 1)

            # 9. Completion assessment
            async with AsyncSessionLocal() as session:
                from core.ai_fleet.services.completion_assessment import CompletionAssessmentService
                assessment = await CompletionAssessmentService().assess(session, project_id)
            # Assessment reports blockers because task criteria aren't formally passed
            self.assertIn("blockers", assessment)
            self.assertEqual(assessment["assessment_version"], "1.0")

            # 10. Create deliverable package
            deliverable = (await client.post(f"/api/projects/{project_id}/deliverables/package", json={"workspace_id": self.workspace_id, "name": "website", "version": "1.0.0", "relative_paths": ["index.html", "package.json"]})).json()
            self.assertIn("checksum", deliverable)
            self.assertIn("manifest", deliverable)
            self.assertEqual(len(deliverable["manifest"]["files"]), 2)
            self.assertIn("download_path", deliverable)
            self.assertIn("assessment", deliverable)

            # 11. Download deliverable
            download = await client.get(deliverable["download_path"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["content-type"], "application/zip")
            self.assertTrue(len(download.content) > 0)

        # Summary: the entire chain from project creation to downloadable deliverable
        # worked through real CLI execution, quality gates, and packaging
        print(f"\n  E2E SCENARIO PASSED:")
        print(f"  Project: {project_id}")
        print(f"  Requirement: {requirement_id}")
        print(f"  Task: {task_id}")
        print(f"  Run: {dispatched['run_id']}")
        print(f"  Quality findings: {len(dispatched['quality_findings'])}")
        print(f"  Deliverable: {deliverable['id']} ({deliverable['archive_size']} bytes)")
        print(f"  Readiness: {deliverable['assessment']['ready']}")


if __name__ == "__main__":
    unittest.main()
