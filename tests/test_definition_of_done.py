import json,unittest
from sqlalchemy import delete
from core.ai_fleet.services.definition_of_done import DefinitionOfDoneService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AcceptanceCriterionRecord,OrchestrationTaskRecord,ProjectRecord,RunAttemptRecord,TaskRun
class DoDTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"dod-p-{id(self)}";self.t=f"dod-t-{id(self)}";self.r=f"dod-r-{id(self)}";self.a=f"dod-a-{id(self)}";self.c=f"dod-c-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="D",slug=f"dod-{id(self)}",project_type="software",owner="local"));s.add(TaskRun(id=self.r,prompt="x",project_id=self.p,status="completed",result_output="agent output"));s.add(RunAttemptRecord(id=self.a,run_id=self.r,attempt_number=1,executor_type="cli",status="completed"));s.add(OrchestrationTaskRecord(id=self.t,project_id=self.p,task_type="build",title="Build",acceptance_json='[{"criterion_id":"tests"}]',dependency_ids_json="[]",current_run_id=self.r,state="running"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AcceptanceCriterionRecord).where(AcceptanceCriterionRecord.id==self.c));await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id==self.t));await s.execute(delete(RunAttemptRecord).where(RunAttemptRecord.id==self.a));await s.execute(delete(TaskRun).where(TaskRun.id==self.r));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_agent_output_alone_never_completes(self):
  async with AsyncSessionLocal() as s:first=await DefinitionOfDoneService().assess(s,self.t);s.add(AcceptanceCriterionRecord(id=self.c,task_id=self.t,criterion_type="test",description="Tests",evaluator="unit_test",severity="high",status="passed",evidence_json=json.dumps([{"run_id":self.r}])));await s.commit();second=await DefinitionOfDoneService().assess(s,self.t)
  self.assertFalse(first["done"]);self.assertIn("criterion_unsatisfied:tests",first["blockers"]);self.assertFalse(first["agent_output_alone_sufficient"]);self.assertTrue(second["done"])
if __name__=="__main__":unittest.main()
