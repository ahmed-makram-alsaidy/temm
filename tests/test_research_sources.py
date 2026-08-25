import unittest,json
from datetime import datetime
from sqlalchemy import delete
from core.ai_fleet.services.research_sources import ResearchSourceService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ResearchQueryRecord,ResearchSourceRecord
class ResearchSourceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db(); self.p=f"rsp-{id(self)}"; self.q=f"rsq-{id(self)}"; self.ids=[]
  async with AsyncSessionLocal() as s: s.add(ProjectRecord(id=self.p,name="R",slug=f"rs-{id(self)}",project_type="research",owner="local")); s.add(ResearchQueryRecord(id=self.q,project_id=self.p,question="q",query_kind="factual_retrieval",source_policy_json="{}",status="draft")); await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(ResearchSourceRecord).where(ResearchSourceRecord.query_id==self.q)); await s.execute(delete(ResearchQueryRecord).where(ResearchQueryRecord.id==self.q)); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p)); await s.commit()
 async def test_hash_change_creates_visible_version(self):
  base={"url":"https://example.com/docs","title":"Docs","source_type":"official_docs","author":"Team","content_hash":"a"*64,"license_id":"docs","confidence":.9}
  async with AsyncSessionLocal() as s: one=await ResearchSourceService().record(s,self.q,base); same=await ResearchSourceService().record(s,self.q,base); two=await ResearchSourceService().record(s,self.q,{**base,"content_hash":"b"*64})
  self.assertEqual(one.id,same.id); self.assertEqual(one.version,1); self.assertEqual(two.version,2); self.assertNotEqual(one.content_hash,two.content_hash); self.assertEqual(two.to_dict()["confidence"],.9)
if __name__=="__main__": unittest.main()
