import unittest
from pathlib import Path
import yaml
class CiContractTests(unittest.TestCase):
 def test_windows_linux_and_required_gates_are_declared(self):
  workflow=yaml.safe_load(Path(".github/workflows/quality.yml").read_text(encoding="utf-8"));text=Path(".github/workflows/quality.yml").read_text(encoding="utf-8");self.assertIn("windows-latest",text);self.assertIn("ubuntu-latest",text)
  for command in ["license_policy","test_license_policy","compileall","test_migrations","test_security","unittest discover","test_e2e.py","npm run lint","tsc -b","npm run build"]:self.assertIn(command,text)
if __name__=="__main__":unittest.main()
