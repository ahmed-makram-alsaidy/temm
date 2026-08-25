import json,unittest
from sqlalchemy import delete
from core.ai_fleet.services.automation_value import AutomationValueService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AcceptanceCriterionRecord,OrchestrationTaskRecord,ProjectRecord,RunAttemptRecord,TaskRun
class AutomationValueTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"avp-{id(self)}";self.tasks=[f"avt-{id(self)}-{i}" for i in range(2)];self.run=f"avr-{id(self)}";self.attempt=f"ava-{id(self)}";self.criterion=f"avc-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="V",slug=f"automation-value-{id(self)}",project_type="software",owner="local"));s.add(TaskRun(id=self.run,prompt="x",project_id=self.p,status="completed"));s.add(RunAttemptRecord(id=self.attempt,run_id=self.run,attempt_number=1,executor_type="cli",status="completed"));s.add(OrchestrationTaskRecord(id=self.tasks[0],project_id=self.p,task_type="work",title="Done",acceptance_json="[]",executor_needs_json=json.dumps({"repeated_work_key":"review"}),state="completed",current_run_id=self.run));s.add(OrchestrationTaskRecord(id=self.tasks[1],project_id=self.p,task_type="work",title="Failed",acceptance_json="[]",state="failed"));s.add(AcceptanceCriterionRecord(id=self.criterion,task_id=self.tasks[0],criterion_type="test",description="x",evaluator="test",severity="high",status="passed",evidence_json='[{"run_id":"x"}]'));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AcceptanceCriterionRecord).where(AcceptanceCriterionRecord.id==self.criterion));await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_(self.tasks)));await s.execute(delete(RunAttemptRecord).where(RunAttemptRecord.id==self.attempt));await s.execute(delete(TaskRun).where(TaskRun.id==self.run));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_failed_unverified_tasks_are_excluded(self):
  async with AsyncSessionLocal() as s:r=await AutomationValueService().aggregate(s,self.p)
  self.assertEqual(r["verified_completed_tasks"],1);self.assertEqual(r["failed_or_unverified_excluded"],1);self.assertEqual(r["provenance"],"measured");self.assertEqual(r["evidence"][0]["task_id"],self.tasks[0])
if __name__=="__main__":unittest.main()
