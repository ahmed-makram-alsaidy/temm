import unittest
from sqlalchemy import delete
from core.ai_fleet.services.need_detector import NeedDetectorService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectBrainFactRecord,ProjectNeedRecord,ProjectRecord,ProjectRequirementRecord
class NeedDetectorTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"nd-{id(self)}";self.f=f"ndf-{id(self)}";self.r=f"ndr-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="N",slug=f"need-detector-{id(self)}",project_type="software",owner="local"));s.add(ProjectBrainFactRecord(id=self.f,project_id=self.p,section="production",fact_key="hosting",value_json="null",truth_state="unknown",provenance="unknown",source_type="unknown",revision=1));s.add(ProjectRequirementRecord(id=self.r,project_id=self.p,title="Blocked",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="blocked",acceptance_json="[]",evidence_json="[]"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.project_id==self.p));await s.execute(delete(ProjectBrainFactRecord).where(ProjectBrainFactRecord.id==self.f));await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id==self.r));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_evidence_linked_needs_are_deduplicated(self):
  finding={"id":"finding-1","code":"secret","severity":"critical","evidence":{"file":"x"},"blocked_nodes":["task-1"]}
  async with AsyncSessionLocal() as s:first=await NeedDetectorService().detect(s,self.p,[],[finding]);second=await NeedDetectorService().detect(s,self.p,[],[finding])
  self.assertEqual(len(first),3);self.assertEqual({x.source_type for x in first},{"brain_fact","requirement","quality_finding"});self.assertEqual({x.id for x in first},{x.id for x in second});self.assertTrue(all(x.impact=="blocking" for x in first))
if __name__=="__main__":unittest.main()
