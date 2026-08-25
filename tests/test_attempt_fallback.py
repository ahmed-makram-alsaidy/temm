import unittest
from sqlalchemy import delete
from core.ai_fleet.services.attempt_fallback import AttemptFallbackService
from core.ai_fleet.services.runs import RunLifecycleService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import RunAttemptRecord,TaskRun
class AttemptFallbackTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.run=f"af-{id(self)}";self.lifecycle=RunLifecycleService();
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id==self.run));await s.execute(delete(TaskRun).where(TaskRun.id==self.run));await s.commit()
 async def test_constraints_bound_persisted_attempts(self):
  async with AsyncSessionLocal() as s:await self.lifecycle.create(s,run_id=self.run,prompt="x",routing_mode="balanced");await self.lifecycle.start(s,self.run)
  routes=[{"route_id":"a","executable":True,"estimated_cost":"0.4"},{"route_id":"b","executable":True,"estimated_cost":"0.4"}]
  async def executor(route,attempt):return {"success":False,"outcome":"failed","error_code":"temporary_failure"}
  async with AsyncSessionLocal() as s:result=await AttemptFallbackService().execute(s,self.run,routes,executor,2,"0.5")
  self.assertEqual(result["constraint_stop_reason"],"max_spend");self.assertEqual(len(result["attempts"]),1);self.assertEqual(result["reserved_spend"],"0.4")
if __name__=="__main__":unittest.main()
