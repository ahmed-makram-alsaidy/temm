import os,tempfile,unittest
from pathlib import Path
from sqlalchemy import delete
from core.ai_fleet.services.asset_ingest import AssetIngestService
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetRecord,ProjectRecord,WorkspaceRecord
class AssetIngestTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db(); self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.w=f"asset-w-{id(self)}"; self.p=f"asset-p-{id(self)}"; self.ids=[]
  async with AsyncSessionLocal() as s: s.add(WorkspaceRecord(id=self.w,name="W",path=str(self.root.resolve()),permission_profile="safe",allowed_shells="[]")); s.add(ProjectRecord(id=self.p,name="P",slug=f"asset-ingest-{id(self)}",project_type="design",owner="local")); await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s: await s.execute(delete(AssetRecord).where(AssetRecord.id.in_(self.ids) if self.ids else AssetRecord.id=="none")); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.p)); await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w)); await s.commit()
  self.tmp.cleanup()
 async def test_signature_hash_relative_path_and_conflict(self):
  (self.root/"logo.png").write_bytes(b"\x89PNG\r\n\x1a\nDATA"); (self.root/"spoof.png").write_bytes(b"%PDF-1.7 data")
  async with AsyncSessionLocal() as s: good=await AssetIngestService().ingest(s,self.w,"logo.png","project",self.p); bad=await AssetIngestService().ingest(s,self.w,"spoof.png"); self.ids=[good.id,bad.id]
  self.assertEqual(good.mime_type,"image/png"); self.assertEqual(good.asset_type,"raster"); self.assertEqual(good.relative_path,"logo.png"); self.assertEqual(len(good.sha256),64); self.assertEqual(bad.state,"type_conflict"); self.assertIsNone(bad.asset_type)
 async def test_traversal_empty_and_symlink_rejected(self):
  (self.root/"empty.txt").write_bytes(b""); outside=self.root.parent/f"outside-{id(self)}.txt"; outside.write_text("x")
  try:
   async with AsyncSessionLocal() as s:
    with self.assertRaises(Exception): await AssetIngestService().ingest(s,self.w,"empty.txt")
    with self.assertRaises(Exception): await AssetIngestService().ingest(s,self.w,str(outside))
    if hasattr(os,"symlink"):
     try: (self.root/"link.txt").symlink_to(outside)
     except OSError: return
     with self.assertRaises(Exception): await AssetIngestService().ingest(s,self.w,"link.txt")
  finally: outside.unlink(missing_ok=True)
if __name__=="__main__": unittest.main()
