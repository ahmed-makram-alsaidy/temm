import unittest
from datetime import datetime,timedelta
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,TaskRun
class ValueApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"vp-{id(self)}";self.other=f"vo-{id(self)}";self.runs=[f"vr-{id(self)}-{i}" for i in range(2)]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="V",slug=f"value-api-{id(self)}",project_type="software",owner="local"));s.add(TaskRun(id=self.runs[0],prompt="x",project_id=self.p,status="completed",financials_json='{"actual_cost":{"amount":"1","currency":"USD","provenance":"provider_reported"}}'));s.add(TaskRun(id=self.runs[1],prompt="x",project_id=self.other,status="completed",financials_json='{"actual_cost":{"amount":"99","currency":"USD","provenance":"provider_reported"}}'));await s.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(TaskRun).where(TaskRun.id.in_(self.runs)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_value_api_is_project_scoped_and_has_no_mixed_total(self):
  now=datetime.utcnow();params={"start":(now-timedelta(days=1)).isoformat(),"end":(now+timedelta(days=1)).isoformat()}
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/value",params=params)
  p=r.json();self.assertEqual(p["financials"]["provider_reported_actual_cost"],"1");self.assertIsNone(p["mixed_total"]);self.assertIn("estimated",p["provenance_groups"])
if __name__=="__main__":unittest.main()
