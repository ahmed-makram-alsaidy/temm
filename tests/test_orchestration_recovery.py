import unittest
from sqlalchemy import delete
from core.ai_fleet.services.orchestration_recovery import OrchestrationRecoveryService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import OrchestrationCheckpointRecord,OrchestrationTaskRecord,ProjectRecord,TaskRun
class RecoveryTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"rp-{id(self)}";self.tasks=[f"rt-{id(self)}-{i}" for i in range(2)];self.run=f"rr-{id(self)}";self.check=None
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="R",slug=f"recovery-{id(self)}",project_type="software",owner="local"));s.add(TaskRun(id=self.run,prompt="x",project_id=self.p,status="running"));s.add(OrchestrationTaskRecord(id=self.tasks[0],project_id=self.p,task_type="x",title="active",acceptance_json="[]",state="ready",current_run_id=self.run));s.add(OrchestrationTaskRecord(id=self.tasks[1],project_id=self.p,task_type="x",title="ready",acceptance_json="[]",state="ready"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:
   if self.check:await s.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.id==self.check))
   await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_(self.tasks)));await s.execute(delete(TaskRun).where(TaskRun.id==self.run));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_restart_prevents_duplicate_dispatch(self):
  async with AsyncSessionLocal() as s:record=await OrchestrationRecoveryService().save(s,self.p,"running",{"node":"x"},self.tasks,self.tasks,["file:a"]);self.check=record.id
  async with AsyncSessionLocal() as s:result=await OrchestrationRecoveryService().recover(s,self.check)
  self.assertEqual(result["safe_ready_queue"],[self.tasks[1]]);self.assertEqual(result["duplicate_dispatch_prevented"],[self.tasks[0]]);self.assertEqual(result["checkpoint"]["lock_keys"],["file:a"])
if __name__=="__main__":unittest.main()
