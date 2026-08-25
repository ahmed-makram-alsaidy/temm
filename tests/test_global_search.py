import unittest
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ProjectRequirementRecord
class GlobalSearchTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.projects=[f"sp-{id(self)}-{i}" for i in range(2)];self.reqs=[f"sr-{id(self)}-{i}" for i in range(2)]
  async with AsyncSessionLocal() as s:
   for i,p in enumerate(self.projects):s.add(ProjectRecord(id=p,name=f"Project {i}",slug=f"search-{id(self)}-{i}",purpose="Clinic system",project_type="software",owner="local"));s.add(ProjectRequirementRecord(id=self.reqs[i],project_id=p,title="Patient search",description="Find patients",requirement_type="functional",source_type="user",truth_state="confirmed",priority="must",status="approved",acceptance_json="[]",evidence_json="[]"))
   await s.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.reqs)));await s.execute(delete(ProjectRecord).where(ProjectRecord.id.in_(self.projects)));await s.commit()
 async def test_project_scope_filters_results_and_excludes_content_secrets(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get("/api/search",params={"q":"patient","project_id":self.projects[0]})
  p=r.json();self.assertTrue(all(x["project_id"] in {self.projects[0],None} for x in p["results"]));self.assertFalse(p["content_searched"]);self.assertFalse(p["secrets_searched"])
if __name__=="__main__":unittest.main()
