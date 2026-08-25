import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, BlueprintProposalRecord, BlueprintProposalRevisionRecord, ProjectRecord, ProjectRequirementRecord, ProjectRequirementRevisionRecord


class BlueprintApprovalApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"blueprint-api-project-{id(self)}"; self.proposal_id = None; self.requirement_ids = []
        async with AsyncSessionLocal() as session: session.add(ProjectRecord(id=self.project_id, name="Blueprint API", slug=f"blueprint-api-{id(self)}", project_type="software", owner="local")); await session.commit()
        self.transport = httpx.ASGITransport(app=app)
        self.content = {"template_id": "website-production", "template_version": "1.0", "approval_required": True, "implementation_started": False, "requirements": [{"title": "Accessible", "description": "Accessibility", "requirement_type": "quality", "priority": "must", "acceptance": []}], "questions": []}
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.requirement_ids: await session.execute(delete(ProjectRequirementRevisionRecord).where(ProjectRequirementRevisionRecord.requirement_id.in_(self.requirement_ids))); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.requirement_ids)))
            if self.proposal_id: await session.execute(delete(BlueprintProposalRevisionRecord).where(BlueprintProposalRevisionRecord.proposal_id == self.proposal_id)); await session.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.id == self.proposal_id))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_review_edit_approve_api(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post(f"/api/projects/{self.project_id}/blueprints", json={"proposal": self.content}); self.assertEqual(created.status_code, 200, created.text); self.proposal_id = created.json()["id"]
            edited_content = dict(self.content); edited_content["requirements"] = [{**self.content["requirements"][0], "title": "Owner accessibility"}]
            edited = await client.patch(f"/api/projects/blueprints/{self.proposal_id}", json={"expected_revision": 1, "content": edited_content})
            approved = await client.post(f"/api/projects/blueprints/{self.proposal_id}/approve", json={"expected_revision": 2, "actor": "owner"}); self.requirement_ids = approved.json()["requirement_ids"]
            repeat = await client.patch(f"/api/projects/blueprints/{self.proposal_id}", json={"expected_revision": 3, "content": edited_content})
        self.assertEqual(edited.json()["content"]["requirements"][0]["title"], "Owner accessibility"); self.assertEqual(approved.json()["proposal"]["status"], "approved"); self.assertEqual(repeat.status_code, 409)


if __name__ == "__main__": unittest.main()
