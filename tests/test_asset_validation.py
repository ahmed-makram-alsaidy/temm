import tempfile,unittest
from pathlib import Path
from sqlalchemy import delete
from core.ai_fleet.services.asset_validation import AssetValidationService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetRecord,AssetUsageRecord,WorkspaceRecord
class AssetValidationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.w=f"avw-{id(self)}";self.a=f"ava-{id(self)}";(self.root/"a.txt").write_text("placeholder")
  async with AsyncSessionLocal() as s:s.add(WorkspaceRecord(id=self.w,name="W",path=str(self.root.resolve()),permission_profile="safe",allowed_shells="[]"));s.add(AssetRecord(id=self.a,scope_type="global",workspace_id=self.w,relative_path="a.txt",asset_type="document",mime_type="text/plain",sha256="a"*64,source_type="user",provenance="user_declared",size_bytes=1,state="ready"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AssetUsageRecord).where(AssetUsageRecord.asset_id==self.a));await s.execute(delete(AssetRecord).where(AssetRecord.id==self.a));await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
  self.tmp.cleanup()
 async def test_findings_have_evidence_and_severity(self):
  async with AsyncSessionLocal() as s:result=await AssetValidationService().validate(s,self.a)
  codes={x["code"] for x in result["findings"]};self.assertTrue({"hash_changed","size_changed","placeholder_content","license_unknown","unused_asset"}<=codes);self.assertFalse(result["valid"]);self.assertTrue(all("severity" in x and "evidence" in x for x in result["findings"]))
 async def test_missing_file_is_critical(self):
  (self.root/"a.txt").unlink()
  async with AsyncSessionLocal() as s:result=await AssetValidationService().validate(s,self.a)
  self.assertEqual(result["findings"][0]["severity"],"critical")
if __name__=="__main__":unittest.main()
