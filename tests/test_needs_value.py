import json,unittest
from sqlalchemy import delete
from core.ai_fleet.services.needs_value import NeedsValueService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectNeedRecord,ProjectRecord
class NeedsValueTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"nvp-{id(self)}";self.ids=[f"nv-{id(self)}-{i}" for i in range(2)]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="N",slug=f"needs-value-{id(self)}",project_type="software",owner="local"));s.add(ProjectNeedRecord(id=self.ids[0],project_id=self.p,need_type="asset",title="A",description="x",source_type="asset",impact="blocking",blocked_nodes_json="[]",state="resolved",resolution_json=json.dumps({"asset_id":"a"}),dedupe_key="asset:a"));s.add(ProjectNeedRecord(id=self.ids[1],project_id=self.p,need_type="dependency",title="D",description="x",source_type="requirement",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="dependency:d"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id.in_(self.ids)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_project_scoped_deduped_counts_require_resolution_evidence(self):
  async with AsyncSessionLocal() as s:r=await NeedsValueService().aggregate(s,self.p)
  self.assertEqual(r["discovered"],2);self.assertEqual(r["resolved_with_evidence"],1);self.assertEqual(r["open"],1);self.assertEqual(r["dedupe_scope"],"project+dedupe_key");self.assertEqual(r["provenance"],"measured")
if __name__=="__main__":unittest.main()
