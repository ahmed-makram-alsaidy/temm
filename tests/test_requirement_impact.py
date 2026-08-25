import unittest

from sqlalchemy import delete

from core.ai_fleet.services.requirement_graph import RequirementGraphService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectRecord, ProjectRequirementEdgeRecord, ProjectRequirementRecord


class RequirementImpactTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"impact-project-{id(self)}"; self.ids = [f"impact-{id(self)}-{i}" for i in range(5)]; self.service = RequirementGraphService()
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Impact", slug=f"impact-{id(self)}", project_type="software", owner="local"))
            for req_id in self.ids: session.add(ProjectRequirementRecord(id=req_id, project_id=self.project_id, title=req_id, requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            await session.commit()
            await self.service.add(session, self.ids[1], self.ids[0], "requires", "Feature requires auth")
            await self.service.add(session, self.ids[2], self.ids[1], "requires", "UI requires feature")
            await self.service.add(session, self.ids[0], self.ids[3], "blocks", "Auth blocks release")
            await self.service.add(session, self.ids[0], self.ids[4], "relates", "Related documentation")
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session: await session.execute(delete(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id == self.project_id)); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids))); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_transitive_impact_has_deterministic_paths_and_reasons(self):
        async with AsyncSessionLocal() as session: result = await self.service.impact(session, self.ids[0])
        by_id = {item["requirement_id"]: item for item in result}
        self.assertEqual(by_id[self.ids[1]]["path"], [self.ids[0], self.ids[1]])
        self.assertEqual(by_id[self.ids[2]]["path"], [self.ids[0], self.ids[1], self.ids[2]])
        self.assertEqual(by_id[self.ids[2]]["reasons"], ["Feature requires auth", "UI requires feature"])
        self.assertEqual(by_id[self.ids[3]]["impact_type"], "downstream")
        self.assertEqual(by_id[self.ids[4]]["impact_type"], "relates")
        self.assertEqual(result, sorted(result, key=lambda item: item["requirement_id"]))


if __name__ == "__main__": unittest.main()
