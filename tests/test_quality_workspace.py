import unittest
from datetime import datetime,timedelta
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ProjectRequirementRecord,QualityWaiverRecord
class QualityWorkspaceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"qw-{id(self)}";self.r=f"qwr-{id(self)}";self.w=f"qww-{id(self)}";finding=f"requirement:{self.r}:evidence"
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="Q",slug=f"quality-{id(self)}",project_type="software",owner="local"));s.add(ProjectRequirementRecord(id=self.r,project_id=self.p,title="Req",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"));s.add(QualityWaiverRecord(id=self.w,project_id=self.p,finding_id=finding,scope_type="project",scope_id=self.p,reason="Accepted risk for release",risk="Missing evidence",owner="owner",expires_at=datetime.utcnow()+timedelta(days=1),status="active"));await s.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(QualityWaiverRecord).where(QualityWaiverRecord.id==self.w));await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id==self.r));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_api_distinguishes_waived_from_blocking_and_never_calls_it_passed(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/quality")
  self.assertEqual(r.status_code,200);p=r.json();self.assertEqual(p["blocking_findings"],[]);self.assertEqual(p["advisory_findings"][0]["status"],"waived");self.assertFalse(p["waivers"][0]["passed"]);self.assertTrue(p["ready"])
if __name__=="__main__":unittest.main()
