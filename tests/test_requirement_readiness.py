import unittest

from sqlalchemy import delete

from core.ai_fleet.services.requirement_graph import RequirementGraphService
from core.ai_fleet.services.requirement_readiness import RequirementReadinessService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectRecord, ProjectRequirementEdgeRecord, ProjectRequirementRecord


class RequirementReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"readiness-project-{id(self)}"
        self.ids = [f"readiness-{id(self)}-{index}" for index in range(2)]
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Readiness", slug=f"readiness-{id(self)}", project_type="software", owner="local"))
            session.add(ProjectRequirementRecord(id=self.ids[0], project_id=self.project_id, title="Feature", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            session.add(ProjectRequirementRecord(id=self.ids[1], project_id=self.project_id, title="Foundation", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            await session.commit()
            await RequirementGraphService().add(session, self.ids[0], self.ids[1], "requires", "Feature requires foundation")

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id == self.project_id))
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids)))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_unresolved_dependency_prevents_ready_and_resolution_propagates(self):
        async with AsyncSessionLocal() as session:
            blocked = await RequirementReadinessService().derive(session, self.ids[0])
            dependency = await session.get(ProjectRequirementRecord, self.ids[1])
            dependency.status = "completed"
            await session.commit()
            ready = await RequirementReadinessService().derive(session, self.ids[0])
        self.assertFalse(blocked["ready"])
        self.assertEqual(blocked["derived_state"], "blocked")
        self.assertEqual(blocked["blockers"][0]["rationale"], "Feature requires foundation")
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["stored_status"], "approved")


if __name__ == "__main__":
    unittest.main()
