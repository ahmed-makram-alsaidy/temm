import unittest
from sqlalchemy import delete
from core.ai_fleet.services.asset_duplicates import AssetDuplicateService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetRecord,WorkspaceRecord
class AssetDuplicateTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db(); self.w=f"dup-w-{id(self)}"; self.ids=[f"dup-{id(self)}-{i}" for i in range(3)]
  async with AsyncSessionLocal() as s:
   s.add(WorkspaceRecord(id=self.w,name="W",path="D:/approved-dup",permission_profile="safe",allowed_shells="[]"))
   for i,asset_id in enumerate(self.ids): s.add(AssetRecord(id=asset_id,scope_type="global",workspace_id=self.w,relative_path=f"{i}.png",asset_type="raster",mime_type="image/png",sha256="a"*64 if i<2 else "b"*64,source_type="user",provenance="user_declared",size_bytes=1,state="ready"))
   await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(AssetRecord).where(AssetRecord.id.in_(self.ids))); await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w)); await s.commit()
 async def test_exact_and_perceptual_candidates_are_advisory_only(self):
  async with AsyncSessionLocal() as s: result=await AssetDuplicateService().detect(s,perceptual=[{"asset_ids":[self.ids[2],self.ids[0]],"similarity":.91,"method":"phash"}])
  self.assertEqual(result["exact_duplicates"][0]["asset_ids"],self.ids[:2]); self.assertEqual(result["perceptual_candidates"][0]["asset_ids"],[self.ids[0],self.ids[2]]); self.assertFalse(result["automatic_merge"]); self.assertFalse(result["automatic_delete"])
if __name__=="__main__": unittest.main()
