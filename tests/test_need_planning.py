import unittest
from sqlalchemy import delete
from core.ai_fleet.services.need_planning import NeedPlanningService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import OrchestrationTaskRecord,ProjectNeedRecord,ProjectRecord
class NeedPlanningTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"np-{id(self)}";self.ids=[f"need-{id(self)}-{i}" for i in range(3)]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="N",slug=f"need-plan-{id(self)}",project_type="software",owner="local"));s.add(ProjectNeedRecord(id=self.ids[0],project_id=self.p,need_type="information",title="Clarify",description="Need answer",source_type="brain_fact",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="a"));s.add(ProjectNeedRecord(id=self.ids[1],project_id=self.p,need_type="asset",title="Logo",description="Need logo",source_type="asset_usage",impact="blocking",blocked_nodes_json="[]",state="open",dedupe_key="b"));s.add(ProjectNeedRecord(id=self.ids[2],project_id=self.p,need_type="research",title="Old",description="Done",source_type="user",impact="advisory",blocked_nodes_json="[]",state="waived",dedupe_key="c"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id==self.p));await s.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.id.in_(self.ids)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_every_open_need_gets_one_resolution_task(self):
  async with AsyncSessionLocal() as s:first=await NeedPlanningService().compile(s,self.p);second=await NeedPlanningService().compile(s,self.p)
  self.assertTrue(first["all_needs_planned"]);self.assertEqual(set(first["need_ids"]),set(self.ids[:2]));self.assertEqual(first["task_ids"],second["task_ids"]);self.assertEqual(len(first["task_ids"]),2)
if __name__=="__main__":unittest.main()
