import unittest

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectBrainFactRecord, ProjectBrainFactRevisionRecord, ProjectRecord


class ProjectBrainServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"brain-service-{id(self)}"
        async with AsyncSessionLocal() as session: session.add(ProjectRecord(id=self.project_id, name="Brain", slug=f"brain-service-{id(self)}", project_type="software", owner="local")); await session.commit()
        self.fact_ids = []; self.transport = httpx.ASGITransport(app=app)
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.fact_ids: await session.execute(delete(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id.in_(self.fact_ids)))
            await session.execute(delete(ProjectBrainFactRecord).where(ProjectBrainFactRecord.project_id == self.project_id)); await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    def payload(self, value="SQLite", truth="confirmed"):
        return {"section": "architecture", "fact_key": "database", "value": value, "truth_state": truth, "provenance": "owner_declared", "source_type": "user", "source_id": "owner", "confidence": 1}

    async def test_merge_is_idempotent_and_conflicts_are_explicit(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=self.payload()); self.fact_ids = [created.json()["id"]]
            same = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=self.payload())
            conflict = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=self.payload("PostgreSQL"))
            updated_payload = self.payload("PostgreSQL"); updated_payload["expected_revision"] = created.json()["revision"]
            updated = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=updated_payload)
            stale_payload = self.payload("MySQL"); stale_payload["expected_revision"] = 1
            stale = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=stale_payload)
            listing = await client.get(f"/api/projects/{self.project_id}/brain", params={"section": "architecture"})
        self.assertEqual(created.status_code, 200); self.assertEqual(same.json()["revision"], 1)
        self.assertEqual(conflict.status_code, 409); self.assertEqual(updated.json()["revision"], 2); self.assertEqual(stale.status_code, 409)
        self.assertEqual(listing.json()[0]["value"], "PostgreSQL")
        async with AsyncSessionLocal() as session: revisions = (await session.execute(select(ProjectBrainFactRevisionRecord).where(ProjectBrainFactRevisionRecord.fact_id == self.fact_ids[0]))).scalars().all()
        self.assertEqual(len(revisions), 2)

    async def test_unknown_and_assumption_are_distinct(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            invalid = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=self.payload("guess", "unknown"))
            unknown_payload = self.payload(None, "unknown"); unknown_payload.update({"fact_key": "hosting", "provenance": "unknown", "source_type": "unknown", "confidence": None})
            unknown = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=unknown_payload)
            assumption_payload = self.payload("Azure", "assumption"); assumption_payload["fact_key"] = "cloud"
            assumption = await client.put(f"/api/projects/{self.project_id}/brain/facts", json=assumption_payload)
        self.assertEqual(invalid.status_code, 422); self.assertEqual(unknown.json()["truth_state"], "unknown"); self.assertEqual(assumption.json()["truth_state"], "assumption")
        self.fact_ids = [unknown.json()["id"], assumption.json()["id"]]


if __name__ == "__main__": unittest.main()
