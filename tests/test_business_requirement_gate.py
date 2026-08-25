import json,unittest
from sqlalchemy import delete
from core.ai_fleet.services.business_requirement_gate import BusinessRequirementGateService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ProjectRequirementRecord
class BusinessGateTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"bg-{id(self)}";self.ids=[f"br-{id(self)}-{i}" for i in range(3)]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="B",slug=f"business-gate-{id(self)}",project_type="business_system",owner="local"));s.add(ProjectRequirementRecord(id=self.ids[0],project_id=self.p,title="Done",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="completed",acceptance_json="[]",evidence_json=json.dumps([{"run_id":"r"}])));s.add(ProjectRequirementRecord(id=self.ids[1],project_id=self.p,title="Missing",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"));s.add(ProjectRequirementRecord(id=self.ids[2],project_id=self.p,title="Waived",requirement_type="constraint",source_type="user",truth_state="confirmed",priority="should",status="waived",acceptance_json="[]",evidence_json="[]",waiver_rationale="Accepted for release",waived_by="owner"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_missing_evidence_blocks_applicable_requirement(self):
  async with AsyncSessionLocal() as s:r=await BusinessRequirementGateService().assess(s,self.p)
  by={x["requirement_id"]:x for x in r["results"]};self.assertEqual(by[self.ids[0]]["status"],"passed");self.assertEqual(by[self.ids[1]]["reason"],"verified_behavior_evidence_missing");self.assertEqual(by[self.ids[2]]["waiver"]["actor"],"owner");self.assertFalse(r["passed"])
if __name__=="__main__":unittest.main()
