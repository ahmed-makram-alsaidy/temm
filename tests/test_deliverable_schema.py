import json,unittest
from sqlalchemy import delete
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import DeliverableRecord,ProjectRecord,WorkspaceRecord
class DeliverableSchemaTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.p=f"dp-{id(self)}";self.w=f"dw-{id(self)}";self.d=f"dd-{id(self)}"
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(DeliverableRecord).where(DeliverableRecord.id==self.d));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
 async def test_deliverable_traces_requirements_assets_runs_and_gates(self):
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="D",slug=f"deliverable-{id(self)}",project_type="software",owner="local"));s.add(WorkspaceRecord(id=self.w,name="W",path="D:/deliver",permission_profile="safe",allowed_shells="[]"));d=DeliverableRecord(id=self.d,project_id=self.p,workspace_id=self.w,name="release",version="1.0",relative_path="dist/release.zip",checksum="a"*64,readiness="blocked",requirement_ids_json='["req"]',asset_ids_json='["asset"]',run_ids_json='["run"]',gate_ids_json='["gate"]');s.add(d);await s.commit()
  p=d.to_dict();self.assertEqual(p["requirement_ids"],["req"]);self.assertEqual(p["asset_ids"],["asset"]);self.assertEqual(p["run_ids"],["run"]);self.assertEqual(p["gate_ids"],["gate"]);self.assertEqual(p["readiness"],"blocked")
if __name__=="__main__":unittest.main()
