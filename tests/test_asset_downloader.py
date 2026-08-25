import tempfile,unittest
from pathlib import Path
from sqlalchemy import delete
from core.ai_fleet.asset_sources import AssetDownloadPolicy
from core.ai_fleet.services.asset_downloader import AssetDownloader
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import WorkspaceRecord
from core.ai_fleet.url_safety import UrlSafetyService
async def chunks(values):
 for value in values:yield value
class DownloaderTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await init_db();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.w=f"dl-{id(self)}"
  async with AsyncSessionLocal() as s:s.add(WorkspaceRecord(id=self.w,name="W",path=str(self.root.resolve()),permission_profile="safe",allowed_shells="[]"));await s.commit()
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id==self.w));await s.commit()
  self.tmp.cleanup()
 async def test_bounded_stream_finalizes_with_hash_and_provenance(self):
  async def stream(url):return {"chunks":chunks([b"abc",b"def"]),"content_type":"image/png","content_length":6,"redirect_chain":[url]}
  async with AsyncSessionLocal() as s:result=await AssetDownloader(stream,UrlSafetyService(lambda h:["93.184.216.34"])).download(s,"https://assets.example/a.png","a.png",AssetDownloadPolicy(True,"approval",self.w,10))
  self.assertEqual((self.root/"a.png").read_bytes(),b"abcdef");self.assertEqual(result["size_bytes"],6);self.assertTrue(result["quarantined_before_finalize"]);self.assertFalse((self.root/"a.png.quarantine").exists())
 async def test_overflow_traversal_and_unsafe_redirect_leave_no_file(self):
  async def overflow(url):return {"chunks":chunks([b"123456"]),"content_type":"image/png","redirect_chain":[url]}
  async def redirect(url):return {"chunks":chunks([b"x"]),"content_type":"image/png","redirect_chain":[url,"https://internal.example/a"]}
  safety=UrlSafetyService(lambda h:["127.0.0.1"] if h=="internal.example" else ["93.184.216.34"])
  async with AsyncSessionLocal() as s:
   with self.assertRaises(Exception):await AssetDownloader(overflow,safety).download(s,"https://assets.example/a","x.png",AssetDownloadPolicy(True,"approval",self.w,5))
   with self.assertRaises(Exception):await AssetDownloader(overflow,safety).download(s,"https://assets.example/a","../x.png",AssetDownloadPolicy(True,"approval",self.w,10))
   with self.assertRaises(Exception):await AssetDownloader(redirect,safety).download(s,"https://assets.example/a","r.png",AssetDownloadPolicy(True,"approval",self.w,10))
  self.assertFalse((self.root/"x.png").exists());self.assertFalse((self.root/"r.png").exists())
if __name__=="__main__":unittest.main()
