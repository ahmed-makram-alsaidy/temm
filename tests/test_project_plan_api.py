import unittest
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.services.orchestration_commands import OrchestrationCommandService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import OrchestrationCheckpointRecord,OrchestrationTaskRecord,ProjectNeedRecord,ProjectRecord
class ProjectPlanApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"ppa-{id(self)}";self.t=f"ppt-{id(self)}";self.n=f"ppn-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="Plan",slug=f"plan-api-{id(self)}",project_type="software",owner="local"));s.add(OrchestrationTaskRecord(id=self.t,project_id=self.p,task_type="work",title="Work",acceptance_json="[]",state="planned"));s.add(ProjectNeedRecord(id=self.n,project_id=self.p,need_type="information",title="Need",description="x",source_type="user",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="x"));await s.commit();self.o=(await OrchestrationCommandService().create(s,self.p)).id
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.id==self.o));await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id==self.t));await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id==self.n));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_plan_api_explains_state_tasks_and_needs(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/plan")
  p=r.json();self.assertEqual(p["orchestrations"][0]["state"],"new");self.assertEqual(p["tasks"][0]["state"],"planned");self.assertEqual(p["needs"][0]["impact"],"blocking")
if __name__=="__main__":unittest.main()
