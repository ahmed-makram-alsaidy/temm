import unittest

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectRecord, ProjectRequirementRecord, ProjectRequirementRevisionRecord


class RequirementServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"requirement-service-{id(self)}"; self.ids = []
        async with AsyncSessionLocal() as session: session.add(ProjectRecord(id=self.project_id, name="Req", slug=f"requirement-service-{id(self)}", project_type="software", owner="local")); await session.commit()
        self.transport = httpx.ASGITransport(app=app)
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids: await session.execute(delete(ProjectRequirementRevisionRecord).where(ProjectRequirementRevisionRecord.requirement_id.in_(self.ids))); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids)))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()
    def payload(self, confirmed=True, evidence=None): return {"title": "Authentication", "requirement_type": "functional", "source_type": "user", "truth_state": "confirmed" if confirmed else "proposed", "priority": "must", "acceptance": [{"statement": "Users sign in"}], "evidence": evidence or [], "owner": "team"}

    async def test_approve_block_waive_require_valid_transitions(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post(f"/api/projects/{self.project_id}/requirements", json=self.payload()); self.ids.append(created.json()["id"])
            approved = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "approved", "actor": "owner"})
            blocked = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "blocked", "actor": "owner"})
            invalid_waiver = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "waived", "actor": "owner", "rationale": "short"})
            waived = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "waived", "actor": "owner", "rationale": "Accepted risk for this release"})
            repeat = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "approved", "actor": "owner"})
        self.assertEqual(approved.json()["status"], "approved"); self.assertEqual(blocked.json()["status"], "blocked"); self.assertEqual(invalid_waiver.status_code, 422); self.assertEqual(waived.json()["waived_by"], "owner"); self.assertEqual(repeat.status_code, 409)
        async with AsyncSessionLocal() as session: revisions = (await session.execute(select(ProjectRequirementRevisionRecord).where(ProjectRequirementRevisionRecord.requirement_id == self.ids[0]))).scalars().all()
        self.assertEqual(len(revisions), 4)

    async def test_approval_and_completion_require_truth_acceptance_and_evidence(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            proposed = await client.post(f"/api/projects/{self.project_id}/requirements", json=self.payload(False)); self.ids.append(proposed.json()["id"])
            invalid = await client.post(f"/api/projects/requirements/{self.ids[0]}/transition", json={"target": "approved", "actor": "owner"})
            approved_req = await client.post(f"/api/projects/{self.project_id}/requirements", json=self.payload(True)); self.ids.append(approved_req.json()["id"])
            await client.post(f"/api/projects/requirements/{self.ids[1]}/transition", json={"target": "approved", "actor": "owner"})
            incomplete = await client.post(f"/api/projects/requirements/{self.ids[1]}/transition", json={"target": "completed", "actor": "owner"})
        self.assertEqual(invalid.status_code, 422); self.assertEqual(incomplete.status_code, 422)


if __name__ == "__main__": unittest.main()
