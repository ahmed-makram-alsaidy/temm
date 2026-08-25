import unittest
from core.ai_fleet.asset_sources import AssetDownloadPolicy,AssetSource,AssetSourceCapability
class Source(AssetSource):
 source_id="fixture";capabilities=frozenset(AssetSourceCapability)
 async def search(self,q):return []
 async def inspect(self,a):return {}
 async def download(self,a,p):p.validate();return {}
 async def license(self,a):return {}
class AssetSourceTests(unittest.TestCase):
 def test_brand_neutral_capabilities(self):self.assertEqual(set(Source().validate().capabilities),set(AssetSourceCapability))
 def test_download_requires_network_approval_workspace_and_bounds(self):
  self.assertIsNotNone(AssetDownloadPolicy(True,"approval","workspace",100).validate())
  for p in [AssetDownloadPolicy(False,"a","w",1),AssetDownloadPolicy(True,None,"w",1),AssetDownloadPolicy(True,"a",None,1),AssetDownloadPolicy(True,"a","w",0)]:
   with self.assertRaises(ValueError):p.validate()
if __name__=="__main__":unittest.main()
