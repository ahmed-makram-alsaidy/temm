import unittest
import uuid

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import (
    AuditRecord,
    BlueprintProposalRecord,
    BlueprintProposalRevisionRecord,
    OrchestrationCheckpointRecord,
    OrchestrationTaskRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    ProjectRequirementRevisionRecord,
)


class ProductSpineApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.suffix = uuid.uuid4().hex[:8]
        self.project_id = None
        self.proposal_id = None
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.project_id:
                requirement_ids = [row.id for row in (await session.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == self.project_id))).scalars().all()]
                task_ids = [row.id for row in (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()]
                await session.execute(delete(ProjectRequirementRevisionRecord).where(ProjectRequirementRevisionRecord.requirement_id.in_(requirement_ids))) if requirement_ids else None
                await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == self.project_id))
                await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
                await session.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.project_id == self.project_id))
                if self.proposal_id:
                    await session.execute(delete(BlueprintProposalRevisionRecord).where(BlueprintProposalRevisionRecord.proposal_id == self.proposal_id))
                    await session.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.id == self.proposal_id))
                await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id))
                await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def test_goal_blueprint_approval_and_plan_contract(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/projects", json={"name": "Spine", "purpose": "Build a verified project outcome", "slug": f"spine-{self.suffix}"})
            self.assertEqual(created.status_code, 200, created.text)
            self.project_id = created.json()["id"]
            blueprint = await client.post(f"/api/projects/{self.project_id}/blueprints/from-goal", json={})
            self.assertEqual(blueprint.status_code, 200, blueprint.text)
            self.proposal_id = blueprint.json()["id"]
            self.assertEqual(blueprint.json()["status"], "proposed")
            approved = await client.post(f"/api/projects/blueprints/{self.proposal_id}/approve", json={"expected_revision": 1, "actor": "local_owner"})
            self.assertEqual(approved.status_code, 200, approved.text)
            requirements = await client.get(f"/api/projects/{self.project_id}/requirements/view")
            self.assertTrue(requirements.json()["requirements"])
            for item in requirements.json()["requirements"]:
                confirmed = await client.patch(f"/api/projects/requirements/{item['id']}", json={"expected_revision": item["revision"], "truth_state": "confirmed"})
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                approved_requirement = await client.post(f"/api/projects/requirements/{item['id']}/transition", json={"target": "approved", "actor": "local_owner"})
                self.assertEqual(approved_requirement.status_code, 200, approved_requirement.text)
            compiled = await client.post(f"/api/projects/{self.project_id}/plan/compile", json={"proposal_id": self.proposal_id})
            self.assertEqual(compiled.status_code, 200, compiled.text)
            self.assertTrue(compiled.json()["task_ids"])
            completion = await client.get(f"/api/projects/{self.project_id}/completion")
            self.assertFalse(completion.json()["ready"])


if __name__ == "__main__":
    unittest.main()
