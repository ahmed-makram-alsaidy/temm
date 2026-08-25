import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.services.context_preparation import ContextPreparationService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import BlueprintProposalRecord, ContextPackRecord, OrchestrationTaskRecord, ProjectDecisionRecord, ProjectNeedRecord, ProjectRecord, ProjectRequirementRecord, WorkspaceRecord


class ContextPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / "context.txt"
        self.file.write_text("architecture\nsk-secretvalue123456789\nconstraints", encoding="utf-8")
        self.second_file = self.root / "constraints.txt"
        self.second_file.write_text("bounded context", encoding="utf-8")
        self.project_id = f"context-project-{id(self)}"
        self.workspace_id = f"context-workspace-{id(self)}"
        self.task_id = f"context-task-{id(self)}"
        self.requirement_id = f"context-requirement-{id(self)}"
        self.blueprint_id = f"context-blueprint-{id(self)}"
        self.need_id = f"context-need-{id(self)}"
        self.decision_id = f"context-decision-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Context", slug=f"context-prep-{id(self)}", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Context", path=str(self.root.resolve()), permission_profile="safe", allowed_shells="[]"))
            session.add(ProjectRequirementRecord(id=self.requirement_id, project_id=self.project_id, title="Requirement", description="Build feature", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json='[{"statement":"Works"}]', evidence_json="[]", revision=2))
            session.add(BlueprintProposalRecord(id=self.blueprint_id, project_id=self.project_id, template_id="website", template_version="1.0", status="approved", content_json='{"sitemap":["home"]}', revision=3))
            session.add(ProjectNeedRecord(id=self.need_id, project_id=self.project_id, requirement_id=self.requirement_id, need_type="information", title="Need", description="Clarify content", source_type="requirement", impact="blocking", blocked_nodes_json="[]", state="open", dedupe_key=f"need-{id(self)}"))
            session.add(ProjectDecisionRecord(id=self.decision_id, project_id=self.project_id, scope_type="project", statement="Use semantic HTML", rationale="Accessibility", impact="Frontend", rule_json='{"semantic":true}', source_type="user", status="approved", revision=1))
            session.add(OrchestrationTaskRecord(id=self.task_id, project_id=self.project_id, task_type="work", title="Work", acceptance_json='[{"criterion_id":"x"}]', context_refs_json=json.dumps([{"source_type": "file", "workspace_id": self.workspace_id, "path": "context.txt"}]), state="ready"))
            await session.commit()
        self.pack_ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ContextPackRecord).where(ContextPackRecord.project_id == self.project_id))
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id == self.task_id))
            await session.execute(delete(ProjectDecisionRecord).where(ProjectDecisionRecord.id == self.decision_id))
            await session.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id == self.need_id))
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id == self.requirement_id))
            await session.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.id == self.blueprint_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.temp.cleanup()

    async def test_preparation_checks_freshness_redaction_budget_and_persists_manifest(self):
        async with AsyncSessionLocal() as session:
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            self.pack_ids.append(result["pack"]["id"])
        self.assertTrue(result["freshness_checked"])
        self.assertTrue(result["redaction_checked"])
        self.assertTrue(result["prepared_immediately_before_attempt"])
        self.assertEqual(result["pack"]["manifest"][0]["content_hash"], result["pack"]["manifest"][0]["version"])
        self.assertTrue(result["pack"]["redactions"][0]["redacted"])

    async def test_plan_compiler_record_refs_prepare_typed_content(self):
        refs = [
            {"source_type": "requirement", "source_id": self.requirement_id, "revision": 2},
            {"source_type": "blueprint", "source_id": self.blueprint_id, "revision": 3},
            {"source_type": "need", "need_id": self.need_id},
            {"source_type": "decision", "source_id": self.decision_id},
        ]
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps(refs)
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 5000)
            self.pack_ids.append(result["pack"]["id"])
        types = [item["source_type"] for item in result["pack"]["manifest"]]
        self.assertEqual(types, ["requirement", "blueprint", "need", "decision"])
        self.assertEqual(len(result["prepared_sources"]), 4)
        self.assertTrue(all(item["content"] for item in result["prepared_sources"]))
        self.assertEqual(result["pack"]["manifest"][0]["version"], "2")

    async def test_quality_finding_ref_resolves_persisted_need(self):
        async with AsyncSessionLocal() as session:
            need = await session.get(ProjectNeedRecord, self.need_id)
            need.source_type = "quality_finding"
            need.source_id = "build:example"
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{"source_type": "quality_finding", "source_id": "build:example"}])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            self.pack_ids.append(result["pack"]["id"])
        self.assertEqual(result["pack"]["manifest"][0]["source_type"], "need")
        self.assertEqual(result["prepared_sources"][0]["source_id"], self.need_id)

    async def test_grouped_files_ref_normalizes_to_individual_bounded_files(self):
        await self._assert_grouped_files_normalize("files")

    async def test_grouped_file_ref_normalizes_to_individual_bounded_files(self):
        await self._assert_grouped_files_normalize("file")

    async def test_completeness_repair_ref_normalizes_to_individual_bounded_files(self):
        await self._assert_grouped_files_normalize("completeness_reconciliation")

    async def test_completeness_finding_ref_resolves_persisted_need(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{
                "source_type": "completeness_reconciliation",
                "dedupe_key": "requirement:context",
                "finding_id": self.need_id,
                "workspace_id": self.workspace_id,
            }])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 1000, "context-run")
            self.pack_ids.append(result["pack"]["id"])
        self.assertEqual(result["pack"]["manifest"][0]["source_type"], "need")
        self.assertEqual(result["prepared_sources"][0]["source_id"], self.need_id)

    async def _assert_grouped_files_normalize(self, source_type):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{
                "source_type": source_type,
                "workspace_id": self.workspace_id,
                "paths": ["context.txt", "constraints.txt"],
            }])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            self.pack_ids.append(result["pack"]["id"])
        manifest = result["pack"]["manifest"]
        self.assertEqual([item["source_type"] for item in manifest], ["file", "file"])
        self.assertEqual([item["source_id"] for item in manifest], ["context.txt", "constraints.txt"])
        self.assertTrue(all(item["workspace_id"] == self.workspace_id for item in manifest))

    async def test_unsupported_context_source_is_rejected(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{"source_type": "unsupported", "source_id": "unknown"}])
            await session.commit()
            with self.assertRaisesRegex(Exception, "Unsupported or unidentified context source") as error:
                await ContextPreparationService().prepare(session, self.task_id, 1000)
        message = str(error.exception)
        self.assertIn(f"task_id={self.task_id}", message)
        self.assertIn("reference_index=0", message)
        self.assertIn("source_type='unsupported'", message)
        self.assertIn("keys=['source_id', 'source_type']", message)
        self.assertNotIn("secretvalue", message)

    async def test_requirement_id_context_ref_is_normalized_to_source_id(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{"source_type": "requirement", "requirement_id": self.requirement_id}])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            self.pack_ids.append(result["pack"]["id"])
        self.assertEqual(result["pack"]["manifest"][0]["source_type"], "requirement")
        self.assertEqual(result["prepared_sources"][0]["source_id"], self.requirement_id)

    async def test_persisted_grouped_historical_tasks_normalize_to_task_sources(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{"source_type": "completeness_reconciliation", "dedupe_key": "history", "historical_task_ids": [self.task_id]}])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            self.pack_ids.append(result["pack"]["id"])
        self.assertEqual(result["pack"]["manifest"][0]["source_type"], "task")
        self.assertEqual(result["prepared_sources"][0]["source_id"], self.task_id)

    async def test_cross_project_record_context_is_rejected(self):
        other = f"other-project-{id(self)}"
        foreign = f"foreign-requirement-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=other, name="Other", slug=f"other-{id(self)}", project_type="software", owner="local"))
            session.add(ProjectRequirementRecord(id=foreign, project_id=other, title="Foreign", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([{"source_type": "requirement", "source_id": foreign}])
            await session.commit()
            with self.assertRaises(Exception):
                await ContextPreparationService().prepare(session, self.task_id, 1000)
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id == foreign))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == other))
            await session.commit()

    async def test_a_budget_admitting_nothing_is_rejected_and_a_missing_file_is_stubbed(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception):
                await ContextPreparationService().prepare(session, self.task_id, 1)
            self.file.unlink()
            # Missing files are now handled gracefully (stub content for restore tasks)
            result = await ContextPreparationService().prepare(session, self.task_id, 1000)
            sources = result["prepared_sources"]
            self.assertTrue(any("does not currently exist" in s.get("content", "") for s in sources))

    async def test_an_over_budget_pack_truncates_by_priority_instead_of_refusing(self):
        """The pack is a record of what the attempt was given; it is not a veto on the
        attempt. The executor reads the workspace itself, so a scope larger than the
        budget costs the pack its lowest-priority sources and costs the task nothing -
        while refusing costs the task everything, which is what production did on
        2026-08-20 to every repair dispatch reconciliation had just composed."""
        large = self.root / "large.txt"
        large.write_text("y" * 8000, encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps([
                {"source_type": "file", "workspace_id": self.workspace_id, "path": "context.txt"},
                {"source_type": "file", "workspace_id": self.workspace_id, "path": "large.txt"},
            ])
            await session.commit()
            result = await ContextPreparationService().prepare(session, self.task_id, 100)
            self.pack_ids.append(result["pack"]["id"])
        self.assertTrue(result["budget"]["truncated"])
        self.assertEqual([item["source_id"] for item in result["prepared_sources"]], ["context.txt"])
        self.assertEqual(result["budget"]["excluded"][0]["source_id"], "large.txt")
        self.assertEqual(result["budget"]["excluded"][0]["reason"], "token_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
