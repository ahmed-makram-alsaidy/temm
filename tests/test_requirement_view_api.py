import unittest
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.services.requirement_graph import RequirementGraphService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ProjectRequirementEdgeRecord,ProjectRequirementRecord
class RequirementViewApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"rvp-{id(self)}";self.ids=[f"rvr-{id(self)}-{i}" for i in range(2)]
  async with AsyncSessionLocal() as s:s.add(ProjectRecord(id=self.p,name="R",slug=f"requirement-view-{id(self)}",project_type="software",owner="local"));s.add(ProjectRequirementRecord(id=self.ids[0],project_id=self.p,title="Feature",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json='[{"statement":"works"}]',evidence_json="[]"));s.add(ProjectRequirementRecord(id=self.ids[1],project_id=self.p,title="Foundation",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"));await s.commit();await RequirementGraphService().add(s,self.ids[0],self.ids[1],"requires","Needs foundation")
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id==self.p));await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.ids)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await s.commit()
 async def test_approved_but_blocked_requirement_is_not_visually_ready_contract(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/requirements/view")
  feature=next(x for x in r.json()["requirements"] if x["id"]==self.ids[0]);self.assertEqual(feature["status"],"approved");self.assertFalse(feature["readiness"]["ready"]);self.assertEqual(feature["readiness"]["derived_state"],"blocked");self.assertEqual(feature["readiness"]["blockers"][0]["requirement_id"],self.ids[1]);self.assertTrue(r.json()["edges"])
if __name__=="__main__":unittest.main()
