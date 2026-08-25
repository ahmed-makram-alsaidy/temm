import json,unittest
from sqlalchemy import delete
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetRecord,AssetTransformJobRecord,WorkspaceRecord
class TransformSchemaTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.w=f"tw-{id(self)}";self.a=f"ta-{id(self)}";self.j=f"tj-{id(self)}"
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AssetTransformJobRecord).where(AssetTransformJobRecord.id==self.j));await s.execute(delete(AssetRecord).where(AssetRecord.id==self.a));await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
 async def test_lineage_retains_tool_parameters_hashes_and_provenance(self):
  async with AsyncSessionLocal() as s:s.add(WorkspaceRecord(id=self.w,name="W",path="D:/transform",permission_profile="safe",allowed_shells="[]"));s.add(AssetRecord(id=self.a,scope_type="global",workspace_id=self.w,relative_path="a.png",asset_type="raster",mime_type="image/png",sha256="a"*64,source_type="user",provenance="owner_declared",size_bytes=1,state="ready"));job=AssetTransformJobRecord(id=self.j,original_asset_id=self.a,tool="image-tool",tool_version="1.2",parameters_json=json.dumps({"width":100}),status="queued",input_hash="a"*64,provenance="deterministic_transform");s.add(job);await s.commit()
  p=job.to_dict();self.assertEqual(p["original_asset_id"],self.a);self.assertEqual(p["parameters"],{"width":100});self.assertEqual(p["input_hash"],"a"*64);self.assertIsNone(p["derivative_asset_id"])
if __name__=="__main__":unittest.main()
