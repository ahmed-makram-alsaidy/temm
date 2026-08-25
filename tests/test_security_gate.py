import tempfile,unittest
from pathlib import Path
from core.ai_fleet.services.security_gate import SecurityGateService
class SecurityGateTests(unittest.TestCase):
 def test_findings_are_redacted_evidenced_and_non_destructive(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/"config.py";source.write_text("api_key='ABCDEFGHIJKLMNOPQRST'\nallow_origins=['*']\ndebug=true",encoding="utf-8");before=source.read_text();result=SecurityGateService().scan(root,[{"id":"ADV-1","package":"pkg","severity":"high"}]);after=source.read_text()
  rules={x["rule"] for x in result["findings"]};self.assertTrue({"secret_api_key","dangerous_cors","debug_enabled","dependency_advisory"}<=rules);self.assertNotIn("ABCDEFGHIJKLMNOPQRST",str(result));self.assertFalse(result["automatic_fix"]);self.assertEqual(before,after);self.assertFalse(result["passed"])
if __name__=="__main__":unittest.main()
