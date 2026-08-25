import unittest
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import OrchestrationCheckpointRecord,ProjectRecord
class OrchestrationApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"oa-{id(self)}";self.o=None
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="O",slug=f"orchestration-api-{id(self)}",project_type="software",owner="local"));await s.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:
   if self.o:await s.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.id==self.o))
   await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_state_commands_are_idempotent_and_conflicts_stable(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:
   created=await c.post("/api/orchestrations",json={"project_id":self.p});self.o=created.json()["id"]
   analyzed=await c.post(f"/api/orchestrations/{self.o}/analyze",json={"payload":{"goal":"x"}});again=await c.post(f"/api/orchestrations/{self.o}/analyze",json={"payload":{}});invalid=await c.post(f"/api/orchestrations/{self.o}/start",json={"payload":{}});status=await c.get(f"/api/orchestrations/{self.o}")
  self.assertEqual(analyzed.json()["state"],"analyzed");self.assertEqual(again.json()["revision"],analyzed.json()["revision"]);self.assertEqual(invalid.status_code,409);self.assertEqual(status.json()["cursor"]["analyze"]["goal"],"x")
if __name__=="__main__":unittest.main()
