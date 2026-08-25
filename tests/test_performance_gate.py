import tempfile,unittest
from pathlib import Path
from core.ai_fleet.services.performance_gate import PerformanceGateService
class PerformanceGateTests(unittest.TestCase):
 def test_build_size_budget_and_environment_are_retained(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/"a.js").write_bytes(b"x"*60);(root/"b.css").write_bytes(b"x"*50);result=PerformanceGateService().assess(root,100,{"duration_ms":{"value":20,"provenance":"measured","method":"wall_clock"}},{"os":"windows","mode":"production"})
  self.assertFalse(result["passed"]);self.assertEqual(result["metrics"]["build_size_bytes"]["value"],110);self.assertEqual(result["environment"]["mode"],"production");self.assertEqual(result["metrics"]["ttft_ms"]["provenance"],"unknown")
if __name__=="__main__":unittest.main()
