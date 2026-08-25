import unittest
from sqlalchemy import delete
from core.ai_fleet.services.completion_assessment import CompletionAssessmentService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectNeedRecord,ProjectRecord,ProjectRequirementRecord
class CompletionAssessmentTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.p=f"ca-{id(self)}";self.r=f"car-{id(self)}";self.n=f"can-{id(self)}"
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id==self.n));await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id==self.r));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_unresolved_requirement_and_need_prevent_done(self):
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="C",slug=f"completion-{id(self)}",project_type="software",owner="local"));s.add(ProjectRequirementRecord(id=self.r,project_id=self.p,title="Req",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"));s.add(ProjectNeedRecord(id=self.n,project_id=self.p,need_type="information",title="Need",description="x",source_type="user",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="x"));await s.commit();blocked=await CompletionAssessmentService().assess(s,self.p);req=await s.get(ProjectRequirementRecord,self.r);req.status="waived";req.waiver_rationale="Accepted for release";req.waived_by="owner";need=await s.get(ProjectNeedRecord,self.n);need.state="waived";await s.commit();ready=await CompletionAssessmentService().assess(s,self.p)
  self.assertFalse(blocked["done"]);self.assertTrue(blocked["blockers"]["requirements"]);self.assertTrue(blocked["blockers"]["needs"]);self.assertTrue(ready["done"])
if __name__=="__main__":unittest.main()
