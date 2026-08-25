import unittest
from datetime import datetime
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import DeliverableRecord,ProjectRecord,WorkspaceRecord
class DeliveryApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"dap-{id(self)}";self.w=f"daw-{id(self)}";self.d=f"dad-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="D",slug=f"delivery-api-{id(self)}",project_type="software",owner="local"));s.add(WorkspaceRecord(id=self.w,name="W",path="D:/delivery",permission_profile="safe",allowed_shells="[]"));s.add(DeliverableRecord(id=self.d,project_id=self.p,workspace_id=self.w,name="release",version="1",relative_path="dist/release.zip",checksum="a"*64,readiness="blocked",requirement_ids_json='["req"]',asset_ids_json='[]',run_ids_json='["run"]',gate_ids_json='["gate"]'));await s.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(DeliverableRecord).where(DeliverableRecord.id==self.d));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
 async def test_api_exposes_exact_included_material_and_readiness(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/deliverables")
  p=r.json()[0];self.assertEqual(p["readiness"],"blocked");self.assertEqual(p["requirement_ids"],["req"]);self.assertEqual(p["run_ids"],["run"]);self.assertEqual(p["checksum"],"a"*64)
if __name__=="__main__":unittest.main()
