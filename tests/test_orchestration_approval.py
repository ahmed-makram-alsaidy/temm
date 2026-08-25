import unittest
from sqlalchemy import delete
from core.ai_fleet.services.approvals import ApprovalService
from core.ai_fleet.services.orchestration_approval import OrchestrationApprovalService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ApprovalRecord,AuditRecord
class OrchestrationApprovalTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.id=None
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:
   if self.id:await s.execute(delete(AuditRecord).where(AuditRecord.resource_id==self.id));await s.execute(delete(ApprovalRecord).where(ApprovalRecord.id==self.id));await s.commit()
 async def test_pause_is_durable_scoped_and_resumes_only_after_approval(self):
  async with AsyncSessionLocal() as s:paused=await OrchestrationApprovalService().escalate(s,"orc-1","spend","Approve spend",{"amount":"10"});self.id=paused["approval"]["id"]
  self.assertEqual(paused["state"],"paused_approval");self.assertTrue(paused["durable"])
  async with AsyncSessionLocal() as s:
   records=await ApprovalService().list(s,"pending");self.assertTrue(any(x.id==self.id for x in records));await ApprovalService().decide(s,self.id,True)
   with self.assertRaises(Exception):await OrchestrationApprovalService().resume(s,self.id,"other","spend")
   resumed=await OrchestrationApprovalService().resume(s,self.id,"orc-1","spend")
  self.assertEqual(resumed["state"],"resumable");self.assertEqual(resumed["approval"]["status"],"consumed")
if __name__=="__main__":unittest.main()
