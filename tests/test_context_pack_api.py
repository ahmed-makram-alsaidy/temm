import unittest
import httpx
from sqlalchemy import delete
from core.ai_fleet.context import ContextSource,ContextSourceType
from core.ai_fleet.main import app
from core.ai_fleet.services.context_packs import ContextPackService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ContextPackRecord,ProjectRecord

class ContextPackApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db(); self.project=f"ctx-api-{id(self)}"
  async with AsyncSessionLocal() as s: s.add(ProjectRecord(id=self.project,name="Ctx",slug=f"ctx-api-{id(self)}",project_type="software",owner="local")); await s.commit(); self.pack=await ContextPackService().create(s,[ContextSource(ContextSourceType.REQUIREMENT,"req","1","owner_declared",project_id=self.project)],10,"measured",project_id=self.project)
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(ContextPackRecord).where(ContextPackRecord.id==self.pack.id)); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.project)); await s.commit()
 async def test_manifest_only_api_excludes_content(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c: response=await c.get(f"/api/projects/{self.project}/context-packs")
  self.assertEqual(response.status_code,200); payload=response.json()[0]; self.assertFalse(payload["content_included"]); self.assertEqual(payload["inspection_scope"],"manifest_only"); self.assertTrue(all("content" not in source for source in payload["manifest"]))

if __name__=="__main__": unittest.main()
