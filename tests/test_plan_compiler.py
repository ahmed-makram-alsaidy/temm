import json,unittest
from sqlalchemy import delete
from core.ai_fleet.services.plan_compiler import PlanCompilerService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import BlueprintProposalRecord,OrchestrationTaskRecord,ProjectNeedRecord,ProjectRecord,ProjectRequirementRecord
class PlanCompilerTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"pc-{id(self)}";self.bp=f"bp-{id(self)}";self.r=f"pr-{id(self)}";self.n=f"pn-{id(self)}";self.nt=f"nt-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="P",slug=f"plan-{id(self)}",project_type="software",owner="local"));s.add(BlueprintProposalRecord(id=self.bp,project_id=self.p,template_id="software",template_version="1",status="approved",content_json="{}",revision=2));s.add(ProjectRequirementRecord(id=self.r,project_id=self.p,title="Feature",description="Build it",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"));s.add(ProjectNeedRecord(id=self.n,project_id=self.p,requirement_id=self.r,need_type="information",title="Clarify",description="Need",source_type="requirement",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="x"));s.add(OrchestrationTaskRecord(id=self.nt,project_id=self.p,task_type="clarification",title="Resolve",acceptance_json='[{"criterion_id":"need"}]',context_refs_json=json.dumps([{"need_id":self.n}]),state="planned"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id==self.p));await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id==self.n));await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id==self.r));await s.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.id==self.bp));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_approved_blueprint_compiles_traceable_graph_without_dispatch(self):
  async with AsyncSessionLocal() as s:result=await PlanCompilerService().compile(s,self.p,self.bp)
  self.assertTrue(result["traceable"]);self.assertFalse(result["dispatch_started"]);self.assertEqual(result["proposal_id"],self.bp);self.assertEqual(result["requirement_ids"],[self.r]);compiled=next(x for x in result["task_ids"] if x!=self.nt);self.assertEqual(result["graph"]["dependencies"][compiled],[self.nt])
if __name__=="__main__":unittest.main()
