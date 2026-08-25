import unittest

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectDecisionRecord, ProjectDecisionRevisionRecord, ProjectRecord


class DecisionStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"decision-service-{id(self)}"; self.decision_ids = []
        async with AsyncSessionLocal() as session: session.add(ProjectRecord(id=self.project_id, name="Decision", slug=f"decision-service-{id(self)}", project_type="software", owner="local")); await session.commit()
        self.transport = httpx.ASGITransport(app=app)
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.decision_ids: await session.execute(delete(ProjectDecisionRevisionRecord).where(ProjectDecisionRevisionRecord.decision_id.in_(self.decision_ids))); await session.execute(delete(ProjectDecisionRecord).where(ProjectDecisionRecord.id.in_(self.decision_ids)))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    def payload(self, statement="Use SQLite", supersedes_id=None):
        return {"scope_type": "component", "scope_id": "database", "statement": statement, "rationale": "Local first", "impact": "No setup", "rule": {"database": statement}, "source_type": "user", "source_id": "owner", "supersedes_id": supersedes_id}

    async def test_approve_requires_explicit_supersession(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            first = await client.post(f"/api/projects/{self.project_id}/decisions", json=self.payload()); self.decision_ids.append(first.json()["id"])
            approved = await client.post(f"/api/projects/decisions/{self.decision_ids[0]}/approve", json={"actor": "owner"})
            competing = await client.post(f"/api/projects/{self.project_id}/decisions", json=self.payload("Use PostgreSQL")); self.decision_ids.append(competing.json()["id"])
            blocked = await client.post(f"/api/projects/decisions/{self.decision_ids[1]}/approve", json={"actor": "owner"})
            replacement = await client.post(f"/api/projects/{self.project_id}/decisions", json=self.payload("Use PostgreSQL", self.decision_ids[0])); self.decision_ids.append(replacement.json()["id"])
            replaced = await client.post(f"/api/projects/decisions/{self.decision_ids[2]}/approve", json={"actor": "owner"})
            active = await client.get(f"/api/projects/{self.project_id}/decisions", params={"status": "approved", "scope_type": "component", "scope_id": "database"})
        self.assertEqual(approved.json()["status"], "approved"); self.assertEqual(blocked.status_code, 409); self.assertEqual(replaced.json()["status"], "approved"); self.assertEqual(active.json()[0]["id"], self.decision_ids[2])
        async with AsyncSessionLocal() as session: old = await session.get(ProjectDecisionRecord, self.decision_ids[0]); revisions = (await session.execute(select(ProjectDecisionRevisionRecord).where(ProjectDecisionRevisionRecord.decision_id == old.id))).scalars().all()
        self.assertEqual(old.status, "superseded"); self.assertEqual(len(revisions), 3)

    async def test_rejected_decision_cannot_transition_again(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post(f"/api/projects/{self.project_id}/decisions", json=self.payload()); self.decision_ids.append(created.json()["id"])
            rejected = await client.post(f"/api/projects/decisions/{self.decision_ids[0]}/reject", json={"actor": "owner"})
            repeat = await client.post(f"/api/projects/decisions/{self.decision_ids[0]}/approve", json={"actor": "owner"})
        self.assertEqual(rejected.json()["status"], "rejected"); self.assertEqual(repeat.status_code, 409)


if __name__ == "__main__": unittest.main()
