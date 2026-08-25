import unittest
from core.ai_fleet.assets import AssetType,classify_asset
class AssetTaxonomyTests(unittest.TestCase):
 def test_all_canonical_types_exist(self): self.assertEqual({x.value for x in AssetType},{"raster","vector","design","font","audio","video","motion","3d","document","data","code","unknown"})
 def test_mime_extension_conflict_is_explicit(self):
  result=classify_asset("photo.png","application/pdf"); self.assertTrue(result["conflict"]); self.assertIsNone(result["canonical_type"]); self.assertEqual(result["extension_type"],"raster"); self.assertEqual(result["mime_type"],"document")
 def test_matching_and_unknown_classification(self):
  self.assertEqual(classify_asset("icon.svg","image/svg+xml")["canonical_type"],"vector"); self.assertEqual(classify_asset("file.unknown",None)["state"],"unknown")
if __name__=="__main__": unittest.main()
