import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectRecord, ProjectRequirementRecord


class RequirementSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): await init_db(); self.project_id = f"requirement-project-{id(self)}"; self.ids = [f"requirement-{id(self)}-{i}" for i in range(2)]
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session: await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids))); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_hierarchy_truth_source_acceptance_and_evidence_are_explicit(self):
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Req", slug=f"req-{id(self)}", project_type="software", owner="local"))
            parent = ProjectRequirementRecord(id=self.ids[0], project_id=self.project_id, title="Authentication", requirement_type="functional", source_type="user", source_id="owner", truth_state="confirmed", priority="must", status="approved", acceptance_json=json.dumps([{"type": "behavior", "statement": "Users can sign in"}]), evidence_json=json.dumps([{"type": "decision", "id": "decision-1"}]), owner="team")
            child = ProjectRequirementRecord(id=self.ids[1], project_id=self.project_id, parent_id=self.ids[0], title="Password reset", requirement_type="functional", source_type="brain", source_id="fact-1", truth_state="proposed", priority="should", status="draft", acceptance_json="[]", evidence_json="[]")
            session.add_all([parent, child]); await session.commit()
        payload = parent.to_dict(); self.assertEqual(payload["acceptance"][0]["type"], "behavior"); self.assertEqual(payload["evidence"][0]["type"], "decision"); self.assertEqual(child.parent_id, parent.id); self.assertNotEqual(payload["truth_state"], payload["status"])


if __name__ == "__main__": unittest.main()
