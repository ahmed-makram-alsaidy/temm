import re
import unittest
from pathlib import Path
from core.ai_fleet.main import app
class ApiDocsTests(unittest.TestCase):
 def test_documented_primary_paths_exist(self):
  text=Path("docs/API.md").read_text(encoding="utf-8");documented=set(re.findall(r"`((?:/api|/health)/[A-Za-z0-9_{}?=./-]+)`",text));paths=set(app.openapi()["paths"])
  for item in documented:
   clean=item.split("?",1)[0]
   if "..." in clean or clean.endswith("/{action}"):continue
   self.assertTrue(clean in paths or any(path.startswith(f"{clean}/") for path in paths) or any(clean.startswith(path.rstrip("}")) for path in paths),clean)
if __name__=="__main__":unittest.main()
