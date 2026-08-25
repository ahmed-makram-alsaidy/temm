import unittest,json
from sqlalchemy import delete
from core.ai_fleet.services.research_claims import ResearchClaimService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ResearchCitationRecord,ResearchClaimRecord,ResearchQueryRecord,ResearchSourceRecord
class ClaimGraphTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db(); self.p=f"cp-{id(self)}";self.q=f"cq-{id(self)}";self.s=f"cs-{id(self)}"
  async with AsyncSessionLocal() as x: x.add(ProjectRecord(id=self.p,name="C",slug=f"claim-{id(self)}",project_type="research",owner="local"));x.add(ResearchQueryRecord(id=self.q,project_id=self.p,question="q",query_kind="factual_retrieval",source_policy_json="{}",status="draft"));x.add(ResearchSourceRecord(id=self.s,query_id=self.q,url="https://example.com",title="T",source_type="official_docs",retrieved_at=__import__("datetime").datetime.utcnow(),content_hash="a"*64,version=1));await x.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as x: await x.execute(delete(ResearchCitationRecord));await x.execute(delete(ResearchClaimRecord));await x.execute(delete(ResearchSourceRecord).where(ResearchSourceRecord.id==self.s));await x.execute(delete(ResearchQueryRecord).where(ResearchQueryRecord.id==self.q));await x.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p));await x.commit()
 async def test_unsupported_claim_becomes_supported_with_exact_version_citation(self):
  async with AsyncSessionLocal() as x: claim=await ResearchClaimService().create(x,self.q,"Package is current");self.assertEqual(claim.status,"unsupported");citation=await ResearchClaimService().cite(x,claim.id,self.s,"Version 2.0 is current","section 1")
  self.assertEqual(claim.status,"supported");self.assertEqual(len(citation.excerpt_hash),64);self.assertEqual(citation.source_id,self.s)
if __name__=="__main__":unittest.main()
