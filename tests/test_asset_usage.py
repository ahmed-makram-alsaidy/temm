import unittest
from sqlalchemy import delete
from core.ai_fleet.services.asset_usage import AssetUsageService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetRecord,AssetUsageRecord,WorkspaceRecord
class AssetUsageTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.w=f"auw-{id(self)}";self.a=f"aua-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(WorkspaceRecord(id=self.w,name="W",path="D:/usage",permission_profile="safe",allowed_shells="[]"));s.add(AssetRecord(id=self.a,scope_type="global",workspace_id=self.w,relative_path="logo.svg",asset_type="vector",mime_type="image/svg+xml",sha256="a"*64,source_type="user",provenance="user_declared",size_bytes=1,state="ready"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AssetUsageRecord).where(AssetUsageRecord.asset_id==self.a));await s.execute(delete(AssetRecord).where(AssetRecord.id==self.a));await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
 async def test_missing_asset_exposes_required_affected_nodes(self):
  async with AsyncSessionLocal() as s:one=await AssetUsageService().link(s,self.a,"component","header","logo",True);same=await AssetUsageService().link(s,self.a,"component","header","logo",True);await AssetUsageService().link(s,self.a,"deliverable","archive","thumbnail",False);impact=await AssetUsageService().affected(s,self.a)
  self.assertEqual(one.id,same.id);self.assertEqual(impact["missing_asset_impact"][0]["target_id"],"header");self.assertEqual(impact["optional_usage"][0]["target_id"],"archive")
if __name__=="__main__":unittest.main()
