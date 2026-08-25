import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectNeedRecord, ProjectRecord, ProjectRequirementRecord


class MissingNeedSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): await init_db(); self.project_id = f"need-project-{id(self)}"; self.req_id = f"need-req-{id(self)}"; self.need_id = f"need-{id(self)}"
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session: await session.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id == self.need_id)); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id == self.req_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()
    async def test_need_has_source_blocker_impact_state_and_resolution(self):
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Need", slug=f"need-{id(self)}", project_type="software", owner="local")); session.add(ProjectRequirementRecord(id=self.req_id, project_id=self.project_id, title="Logo", requirement_type="asset", source_type="user", truth_state="confirmed", priority="must", status="blocked", acceptance_json="[]", evidence_json="[]"))
            need = ProjectNeedRecord(id=self.need_id, project_id=self.project_id, requirement_id=self.req_id, need_type="asset", title="Approved logo", description="Need source SVG", source_type="requirement", source_id=self.req_id, impact="blocking", blocked_nodes_json=json.dumps([self.req_id, "deliverable-home"]), state="open", dedupe_key="asset:approved-logo")
            session.add(need); await session.commit()
        payload = need.to_dict(); self.assertEqual(payload["source_type"], "requirement"); self.assertEqual(payload["impact"], "blocking"); self.assertEqual(payload["state"], "open"); self.assertEqual(payload["blocked_nodes"], [self.req_id, "deliverable-home"]); self.assertIsNone(payload["resolution"])


if __name__ == "__main__": unittest.main()
