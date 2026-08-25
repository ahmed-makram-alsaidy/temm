import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.services.quality_repair_decomposition import QualityRepairDecompositionService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import OrchestrationTaskRecord, ProjectNeedRecord, ProjectRecord


class QualityRepairDecompositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = __import__("uuid").uuid4().hex[:8]
        self.project_id = f"repair-project-{suffix}"
        self.finding_id = f"repair-finding-{suffix}"
        self.parent_id = f"repair-parent-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Repair", slug=f"repair-{suffix}", project_type="software", owner="local"))
            session.add(ProjectNeedRecord(id=self.finding_id, project_id=self.project_id, need_type="capability", title="Repair quality", description="repair", source_type="quality_finding", source_id=f"build:{suffix}", impact="blocking", blocked_nodes_json='["build"]', state="open", dedupe_key=f"repair:{suffix}"))
            session.add(OrchestrationTaskRecord(id=self.parent_id, project_id=self.project_id, task_type="implementation", title="Parent repair", acceptance_json='[{"criterion_id":"parent","description":"Repair passes"}]', state="failed"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
            await session.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id == self.finding_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_decomposition_is_parent_linked_ordered_and_idempotent(self):
        async with AsyncSessionLocal() as session:
            first = await QualityRepairDecompositionService().decompose(session, self.finding_id, self.parent_id)
            second = await QualityRepairDecompositionService().decompose(session, self.finding_id, self.parent_id)
        self.assertEqual(first["graph_version"], "quality_repair_v1")
        self.assertEqual(len(first["child_tasks"]), 5)
        self.assertEqual([item["id"] for item in first["child_tasks"]], [item["id"] for item in second["child_tasks"]])
        children = first["child_tasks"]
        self.assertEqual(children[0]["dependency_ids"], [])
        for previous, current in zip(children, children[1:]):
            self.assertEqual(current["dependency_ids"], [previous["id"]])
        self.assertTrue(all(any(ref.get("parent_task_id") == self.parent_id for ref in item["context_refs"]) for item in children))
        self.assertIn("multi_file_edit", children[0]["executor_needs"]["capabilities"])


if __name__ == "__main__":
    unittest.main()
