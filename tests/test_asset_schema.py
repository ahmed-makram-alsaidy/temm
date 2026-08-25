import unittest
from sqlalchemy import delete,inspect
from core.ai_fleet.storage.database import AsyncSessionLocal,engine,init_db
from core.ai_fleet.storage.models import AssetRecord,ProjectRecord,WorkspaceRecord
class AssetSchemaTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self): await init_db(); self.ids={"p":f"asset-p-{id(self)}","w":f"asset-w-{id(self)}","a":f"asset-{id(self)}"}
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(AssetRecord).where(AssetRecord.id==self.ids["a"])); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.ids["p"])); await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.ids["w"])); await s.commit()
 async def test_project_asset_is_traceable_without_absolute_path(self):
  async with AsyncSessionLocal() as s:
   s.add(ProjectRecord(id=self.ids["p"],name="Asset",slug=f"asset-{id(self)}",project_type="design",owner="local")); s.add(WorkspaceRecord(id=self.ids["w"],name="W",path="D:/approved",permission_profile="safe",allowed_shells="[]")); a=AssetRecord(id=self.ids["a"],scope_type="project",project_id=self.ids["p"],workspace_id=self.ids["w"],relative_path="assets/logo.svg",asset_type="vector",mime_type="image/svg+xml",sha256="a"*64,source_type="user",source_id="owner",provenance="owner_declared",license_id="owned",size_bytes=100,state="ready"); s.add(a); await s.commit()
  p=a.to_dict(); self.assertEqual(p["relative_path"],"assets/logo.svg"); self.assertNotIn("absolute_path",p)
  async with engine.connect() as c: cols=await c.run_sync(lambda sync:{x["name"] for x in inspect(sync).get_columns("assets")})
  self.assertNotIn("absolute_path",cols); self.assertTrue({"scope_type","project_id","workspace_id","relative_path","asset_type","mime_type","sha256","provenance","license_id","size_bytes","state"}<=cols)
if __name__=="__main__": unittest.main()
