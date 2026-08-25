import unittest
from core.ai_fleet.value import ValueMetric
class ValueContractTests(unittest.TestCase):
 def test_measured_and_estimated_are_explicit(self):
  measured=ValueMetric("m","p","tasks","2","count","measured","2026-01-01","2026-02-01",evidence=[{"task_id":"t"}]).validate();estimated=ValueMetric("e","p","time","10","hours","estimated","2026-01-01","2026-02-01","tasks*minutes/60",confidence=.5,assumptions={"minutes":30}).validate();self.assertEqual(measured.provenance,"measured");self.assertEqual(estimated.formula,"tasks*minutes/60")
 def test_invalid_unknown_measured_estimated_fail(self):
  with self.assertRaises(ValueError):ValueMetric("u","p","x","1","count","unknown","a","b").validate()
  with self.assertRaises(ValueError):ValueMetric("m","p","x","1","count","measured","a","b").validate()
  with self.assertRaises(ValueError):ValueMetric("e","p","x","1","count","estimated","a","b").validate()
if __name__=="__main__":unittest.main()
