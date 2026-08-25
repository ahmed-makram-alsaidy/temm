import unittest
from sqlalchemy import delete
from core.ai_fleet.context import ContextSource,ContextSourceType
from core.ai_fleet.services.context_packs import ContextPackService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import ContextPackRecord

class ContextPackTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self): await init_db(); self.id=None; self.service=ContextPackService()
 async def asyncTearDown(self):
  if self.id:
   async with AsyncSessionLocal() as s: await s.execute(delete(ContextPackRecord).where(ContextPackRecord.id==self.id)); await s.commit()
 async def test_manifest_persists_evidence_and_detects_stale_sources(self):
  sources=[ContextSource(ContextSourceType.FILE,"a.py","v1","observed","a"*64,"w","p"),ContextSource(ContextSourceType.REQUIREMENT,"req","2","owner_declared",project_id="p")]
  async with AsyncSessionLocal() as s: pack=await self.service.create(s,sources,100,"estimated","chars/4",[{"source_id":"a.py","count":1}],project_id="p"); self.id=pack.id
  payload=pack.to_dict(); self.assertEqual(payload["token_method"],"chars/4"); self.assertEqual(payload["redactions"][0]["count"],1)
  fresh=self.service.freshness(pack,{"a.py":{"version":"v1","content_hash":"a"*64},"req":{"version":"2"}}); self.assertTrue(fresh["reproducible"])
  stale=self.service.freshness(pack,{"a.py":{"version":"v2","content_hash":"b"*64}}); self.assertFalse(stale["reproducible"]); self.assertEqual({x["reason"] for x in stale["stale_sources"]},{"version_changed","source_missing"})

if __name__=="__main__": unittest.main()
