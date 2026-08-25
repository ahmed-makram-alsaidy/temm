import json,unittest
from datetime import datetime
from sqlalchemy import delete
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ProjectRecord,ResearchQueryRecord
class ResearchSchemaTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self): await init_db(); self.project=f"research-{id(self)}"; self.query=f"query-{id(self)}"
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(ResearchQueryRecord).where(ResearchQueryRecord.id==self.query)); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.project)); await s.commit()
 async def test_query_distinguishes_factual_retrieval_from_generation(self):
  async with AsyncSessionLocal() as s:
   s.add(ProjectRecord(id=self.project,name="Research",slug=f"research-{id(self)}",project_type="research",owner="local")); q=ResearchQueryRecord(id=self.query,project_id=self.project,question="Current package version?",query_kind="factual_retrieval",freshness_after=datetime(2026,1,1),source_policy_json=json.dumps({"allowed_types":["official_docs"],"network":"approval_required"}),claim_ids_json="[]",project_usage_json=json.dumps([{"requirement_id":"req-1"}]),status="draft"); s.add(q); await s.commit()
  p=q.to_dict(); self.assertEqual(p["query_kind"],"factual_retrieval"); self.assertEqual(p["source_policy"]["allowed_types"],["official_docs"]); self.assertNotIn("answer",p); self.assertEqual(p["project_usage"][0]["requirement_id"],"req-1")
if __name__=="__main__": unittest.main()
