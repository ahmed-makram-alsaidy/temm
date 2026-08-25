import tempfile,unittest
from pathlib import Path
import yaml
from core.ai_fleet.plugin_kit import PluginKit
from core.ai_fleet.plugin_protocol import PluginManifest
class PluginKitTests(unittest.TestCase):
 def test_all_requested_scaffolds_pass_manifest_conformance(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   for kind in ["agent","provider","skill","research","asset","gate"]:
    path=PluginKit().scaffold(root,f"example-{kind}",kind);manifest=PluginManifest.parse(yaml.safe_load((path/"manifest.yaml").read_text()));self.assertEqual(manifest.plugin_id,f"example-{kind}");self.assertTrue((path/"adapter.py").is_file());self.assertTrue((path/"test_adapter.py").is_file())
 def test_existing_folder_and_invalid_kind_are_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);PluginKit().scaffold(root,"example-agent","agent")
   with self.assertRaises(FileExistsError):PluginKit().scaffold(root,"example-agent","agent")
   with self.assertRaises(ValueError):PluginKit().scaffold(root,"example-theme","theme")
if __name__=="__main__":unittest.main()
