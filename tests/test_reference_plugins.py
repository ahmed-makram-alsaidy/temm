import unittest
from pathlib import Path
import yaml
from core.ai_fleet.plugin_protocol import PluginManifest
class ReferencePluginTests(unittest.TestCase):
 def test_all_reference_types_are_conformant_and_secret_free(self):
  root=Path("examples/plugins");folders=sorted(path for path in root.iterdir() if path.is_dir());self.assertEqual(len(folders),6);types=set()
  for folder in folders:
   manifest=PluginManifest.parse(yaml.safe_load((folder/"manifest.yaml").read_text(encoding="utf-8")));types.add(manifest.plugin_type.value);text="\n".join(path.read_text(encoding="utf-8") for path in folder.iterdir() if path.is_file());self.assertNotIn("api_key=",text.lower());self.assertTrue((folder/manifest.entrypoint).is_file())
  self.assertEqual(types,{"agent","provider","skill","research","asset_source","quality_gate"})
if __name__=="__main__":unittest.main()
