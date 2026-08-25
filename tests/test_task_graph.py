import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.services.task_graph import TaskGraphService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import OrchestrationTaskRecord, ProjectRecord


class TaskGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"graph-project-{id(self)}"
        self.ids = [f"graph-task-{id(self)}-{index}" for index in range(4)]
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Graph", slug=f"task-graph-{id(self)}", project_type="software", owner="local"))
            dependencies = [[], [self.ids[0]], [self.ids[0]], [self.ids[1], self.ids[2]]]
            states = ["completed", "planned", "planned", "planned"]
            for index, task_id in enumerate(self.ids):
                session.add(OrchestrationTaskRecord(id=task_id, project_id=self.project_id, task_type="work", title=str(index), dependency_ids_json=json.dumps(dependencies[index]), acceptance_json='[{"criterion_id":"x"}]', state=states[index]))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_(self.ids)))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_order_critical_path_and_ready_queue_are_deterministic(self):
        async with AsyncSessionLocal() as session:
            result = await TaskGraphService().derive(session, self.project_id)
        self.assertEqual(result["topological_order"], self.ids)
        self.assertEqual(result["critical_path"], [self.ids[0], self.ids[2], self.ids[3]])
        self.assertEqual(result["ready_queue"], [self.ids[1], self.ids[2]])

    async def test_cycle_prevents_derivation_and_dispatch(self):
        async with AsyncSessionLocal() as session:
            first = await session.get(OrchestrationTaskRecord, self.ids[0])
            first.dependency_ids_json = json.dumps([self.ids[3]])
            await session.commit()
            with self.assertRaises(Exception):
                await TaskGraphService().derive(session, self.project_id)


if __name__ == "__main__":
    unittest.main()
