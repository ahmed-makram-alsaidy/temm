import tempfile,unittest,zipfile,io
from pathlib import Path
from core.ai_fleet.services.packaging import PackagingService
class PackagingTests(unittest.TestCase):
 def test_workspace_package_is_reproducible_and_manifested(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/"src").mkdir();(root/"src/a.txt").write_text("a");(root/"README.md").write_text("docs");one=PackagingService().package(str(root),["src/a.txt","README.md"]);two=PackagingService().package(str(root),["README.md","src/a.txt"])
  self.assertEqual(one["archive_sha256"],two["archive_sha256"]);self.assertEqual([x["path"] for x in one["manifest"]["files"]],["README.md","src/a.txt"]);self.assertTrue(one["reproducible"])
  with zipfile.ZipFile(io.BytesIO(one["archive"])) as z:self.assertIn("MANIFEST.json",z.namelist())
 def test_traversal_and_secrets_are_blocked(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/"secret.txt").write_text("api_key=ABCDEFGHIJKLMNOPQRST")
   with self.assertRaises(Exception):PackagingService().package(str(root),["secret.txt"])
   with self.assertRaises(Exception):PackagingService().package(str(root),["../outside"])
if __name__=="__main__":unittest.main()
