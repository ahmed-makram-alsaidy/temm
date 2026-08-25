import unittest
from sqlalchemy import delete
from core.ai_fleet.services.acceptance import AcceptanceService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AcceptanceCriterionRecord,OrchestrationTaskRecord,ProjectRecord
class AcceptanceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"ac-p-{id(self)}";self.t=f"ac-t-{id(self)}";self.ids=[]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="A",slug=f"acceptance-{id(self)}",project_type="software",owner="local"));s.add(OrchestrationTaskRecord(id=self.t,project_id=self.p,task_type="test",title="Test",acceptance_json="[]",state="planned"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AcceptanceCriterionRecord).where(AcceptanceCriterionRecord.id.in_(self.ids) if self.ids else AcceptanceCriterionRecord.id=="none"));await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id==self.t));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_pass_requires_evidence_and_waiver_is_explicit(self):
  async with AsyncSessionLocal() as s:
   passed=await AcceptanceService().create(s,self.t,{"criterion_type":"test","description":"Tests pass","evaluator":"unit_test","severity":"high"});self.ids.append(passed.id)
   with self.assertRaises(Exception):await AcceptanceService().decide(s,passed.id,"passed")
   await AcceptanceService().decide(s,passed.id,"passed",[{"run_id":"run-1"}])
   waived=await AcceptanceService().create(s,self.t,{"criterion_type":"review","description":"Review","evaluator":"human","severity":"medium"});self.ids.append(waived.id)
   with self.assertRaises(Exception):await AcceptanceService().decide(s,waived.id,"waived",waiver={"actor":"owner","rationale":"short"})
   result=await AcceptanceService().decide(s,waived.id,"waived",waiver={"actor":"owner","rationale":"Accepted risk for release"})
  self.assertEqual(result.to_dict()["waiver"]["actor"],"owner");self.assertEqual(passed.status,"passed")
if __name__=="__main__":unittest.main()
