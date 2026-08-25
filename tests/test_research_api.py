import unittest
from datetime import datetime
import httpx
from sqlalchemy import delete
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ResearchCitationRecord,ResearchClaimRecord,ResearchQueryRecord,ResearchSourceRecord
class ResearchApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.p=f"rap-{id(self)}";self.q=f"raq-{id(self)}";self.s=f"ras-{id(self)}";self.claims=[f"rac-{id(self)}-{i}" for i in range(2)];self.citation=f"citation-{id(self)}"
  async with AsyncSessionLocal() as x:x.add(ProjectRecord(id=self.p,name="R",slug=f"research-api-{id(self)}",project_type="research",owner="local"));x.add(ResearchQueryRecord(id=self.q,project_id=self.p,question="Current version?",query_kind="factual_retrieval",source_policy_json="{}",project_usage_json='[{"requirement_id":"req"}]',status="completed"));x.add(ResearchSourceRecord(id=self.s,query_id=self.q,url="https://example.com",title="Docs",source_type="official_docs",retrieved_at=datetime.utcnow(),content_hash="a"*64,version=1,confidence=.9));x.add(ResearchClaimRecord(id=self.claims[0],query_id=self.q,project_id=self.p,statement="Supported",status="supported"));x.add(ResearchClaimRecord(id=self.claims[1],query_id=self.q,project_id=self.p,statement="Unknown",status="unsupported"));x.add(ResearchCitationRecord(id=self.citation,claim_id=self.claims[0],source_id=self.s,excerpt="Evidence",excerpt_hash="b"*64,locator="line 1"));await x.commit()
  self.transport=httpx.ASGITransport(app=app)
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as x:await x.execute(delete(ResearchCitationRecord));await x.execute(delete(ResearchClaimRecord).where(ResearchClaimRecord.id.in_(self.claims)));await x.execute(delete(ResearchSourceRecord).where(ResearchSourceRecord.id==self.s));await x.execute(delete(ResearchQueryRecord).where(ResearchQueryRecord.id==self.q));await x.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await x.commit()
 async def test_api_keeps_unsupported_claim_visible(self):
  async with httpx.AsyncClient(transport=self.transport,base_url="http://test") as c:r=await c.get(f"/api/projects/{self.p}/research")
  claims=r.json()[0]["claims"];self.assertEqual({x["status"] for x in claims},{"supported","unsupported"});self.assertEqual(next(x for x in claims if x["status"]=="unsupported")["citations"],[])
if __name__=="__main__":unittest.main()
