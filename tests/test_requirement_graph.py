import unittest

from sqlalchemy import delete

from core.ai_fleet.services.requirement_graph import RequirementGraphService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectRecord, ProjectRequirementEdgeRecord, ProjectRequirementRecord


class RequirementGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.projects = [f"graph-project-{id(self)}-{i}" for i in range(2)]; self.ids = [f"graph-req-{id(self)}-{i}" for i in range(4)]
        async with AsyncSessionLocal() as session:
            session.add_all([ProjectRecord(id=self.projects[0], name="One", slug=f"graph-one-{id(self)}", project_type="software", owner="local"), ProjectRecord(id=self.projects[1], name="Two", slug=f"graph-two-{id(self)}", project_type="software", owner="local")])
            for index, req_id in enumerate(self.ids): session.add(ProjectRequirementRecord(id=req_id, project_id=self.projects[0] if index < 3 else self.projects[1], title=req_id, requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            await session.commit()
        self.service = RequirementGraphService()
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session: await session.execute(delete(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.source_id.in_(self.ids))); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids))); await session.execute(delete(ProjectRecord).where(ProjectRecord.id.in_(self.projects))); await session.commit()

    async def test_ordering_cycle_is_rejected_and_duplicate_is_idempotent(self):
        async with AsyncSessionLocal() as session:
            first = await self.service.add(session, self.ids[0], self.ids[1], "requires", "A requires B")
            duplicate = await self.service.add(session, self.ids[0], self.ids[1], "requires", "A requires B")
            await self.service.add(session, self.ids[1], self.ids[2], "blocks", "B blocks C")
            with self.assertRaises(Exception): await self.service.add(session, self.ids[2], self.ids[0], "requires", "cycle")
        self.assertEqual(first.id, duplicate.id)

    async def test_cross_project_and_self_edges_are_rejected_but_conflict_is_nonordering(self):
        async with AsyncSessionLocal() as session:
            conflict = await self.service.add(session, self.ids[0], self.ids[1], "conflicts", "Mutually exclusive")
            reverse = await self.service.add(session, self.ids[1], self.ids[0], "conflicts", "Mutually exclusive")
            with self.assertRaises(Exception): await self.service.add(session, self.ids[0], self.ids[3], "relates", "cross")
            with self.assertRaises(Exception): await self.service.add(session, self.ids[0], self.ids[0], "requires", "self")
        self.assertNotEqual(conflict.id, reverse.id)


if __name__ == "__main__": unittest.main()
