import unittest
from datetime import datetime,timedelta
from sqlalchemy import delete
from core.ai_fleet.services.quality_waivers import QualityWaiverService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,QualityWaiverRecord
class WaiverTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.p=f"wp-{id(self)}";self.id=None
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:
   if self.id:await s.execute(delete(QualityWaiverRecord).where(QualityWaiverRecord.id==self.id))
   await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_explicit_waiver_never_becomes_passed(self):
  now=datetime.utcnow()
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="W",slug=f"waiver-{id(self)}",project_type="software",owner="local"));await s.commit();record=await QualityWaiverService().create(s,self.p,"finding-1","task","task-1","Accepted risk for this release","Potential security exposure","owner",now+timedelta(days=1));self.id=record.id
  current=QualityWaiverService().current(record,now);expired=QualityWaiverService().current(record,now+timedelta(days=2));self.assertTrue(current["effective"]);self.assertFalse(current["passed"]);self.assertEqual(current["finding_status"],"waived");self.assertFalse(expired["effective"])
if __name__=="__main__":unittest.main()
