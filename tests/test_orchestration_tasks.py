import unittest

from sqlalchemy import delete

from core.ai_fleet.services.orchestration_tasks import OrchestrationTaskService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import OrchestrationTaskRecord, ProjectRecord, ProjectRequirementRecord, TaskRun


class OrchestrationTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.project_id = f"task-project-{id(self)}"
        self.requirement_id = f"task-requirement-{id(self)}"
        self.run_id = f"task-run-{id(self)}"
        self.task_ids = []
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Tasks", slug=f"tasks-{id(self)}", project_type="software", owner="local"))
            session.add(ProjectRequirementRecord(id=self.requirement_id, project_id=self.project_id, title="Feature", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json="[]", evidence_json="[]"))
            session.add(TaskRun(id=self.run_id, prompt="work", project_id=self.project_id, status="completed"))
            await session.commit()
        self.service = OrchestrationTaskService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_(self.task_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id == self.run_id))
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id == self.requirement_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_completion_cannot_bypass_dependencies_criteria_or_run(self):
        values = {"task_type": "implementation", "title": "Build", "requirement_ids": [self.requirement_id], "acceptance": [{"criterion_id": "tests", "description": "Tests pass"}], "context_refs": [{"source_id": self.requirement_id}], "executor_needs": {"capabilities": ["coding"]}}
        async with AsyncSessionLocal() as session:
            dependency = await self.service.create(session, self.project_id, {**values, "title": "Dependency"})
            self.task_ids.append(dependency.id)
            task = await self.service.create(session, self.project_id, {**values, "dependency_ids": [dependency.id]})
            self.task_ids.append(task.id)
            with self.assertRaises(Exception):
                await self.service.transition(session, task.id, "ready")
            await self.service.transition(session, dependency.id, "ready")
            await self.service.transition(session, dependency.id, "running")
            await self.service.transition(session, dependency.id, "completed", [{"criterion_id": "tests", "status": "passed", "evidence": {"run_id": self.run_id}}], self.run_id)
            await self.service.transition(session, task.id, "ready")
            await self.service.transition(session, task.id, "running")
            with self.assertRaises(Exception):
                await self.service.transition(session, task.id, "completed", [], self.run_id)
            completed = await self.service.transition(session, task.id, "completed", [{"criterion_id": "tests", "status": "passed", "evidence": {"run_id": self.run_id}}], self.run_id)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.current_run_id, self.run_id)


if __name__ == "__main__":
    unittest.main()
