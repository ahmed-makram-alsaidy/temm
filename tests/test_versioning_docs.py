import unittest
from pathlib import Path
from core.ai_fleet.domain import CAPABILITY_SCHEMA_VERSION,DOMAIN_SCHEMA_VERSION,STATE_SCHEMA_VERSION
from core.ai_fleet.errors import ERROR_SCHEMA_VERSION
from core.ai_fleet.events import EVENT_SCHEMA_VERSION
from core.ai_fleet.plugin_protocol import PLUGIN_PROTOCOL_VERSION
from core.ai_fleet.providers import PROVIDER_PROTOCOL_VERSION
from core.ai_fleet.storage.migrations import MIGRATIONS
class VersioningDocsTests(unittest.TestCase):
 def test_documented_versions_match_code_and_migrations(self):
  text=Path("docs/VERSIONING.md").read_text(encoding="utf-8")
  for value in [CAPABILITY_SCHEMA_VERSION,DOMAIN_SCHEMA_VERSION,STATE_SCHEMA_VERSION,ERROR_SCHEMA_VERSION,EVENT_SCHEMA_VERSION,PLUGIN_PROTOCOL_VERSION,PROVIDER_PROTOCOL_VERSION]:self.assertIn(value,text)
  self.assertIn(f"migration {MIGRATIONS[-1].version}",text)
  self.assertIn("Never edit an applied migration checksum",text)
if __name__=="__main__":unittest.main()
