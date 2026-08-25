import unittest
from core.ai_fleet.services.rework_value import ReworkValueService
class ReworkValueTests(unittest.TestCase):
 def test_measured_count_and_estimated_formula_are_separate(self):
  result=ReworkValueService().calculate([{"id":"f1","status":"resolved","evidence":{"run":"r"}},{"id":"f2","status":"open","evidence":None}],{"hours_per_defect":2,"hourly_value":10});self.assertEqual(result["defects_caught"]["value"],1);self.assertEqual(result["defects_caught"]["provenance"],"measured");self.assertEqual(result["estimated_rework_prevented"]["value"],"20.00");self.assertEqual(result["estimated_rework_prevented"]["provenance"],"estimated")
 def test_assumptions_are_editable_and_validated(self):
  one=ReworkValueService().calculate([{"id":"f","status":"open","evidence":{}}],{"hours_per_defect":1,"hourly_value":5});two=ReworkValueService().calculate([{"id":"f","status":"open","evidence":{"x":1}}],{"hours_per_defect":3,"hourly_value":5});self.assertNotEqual(one["estimated_rework_prevented"]["value"],two["estimated_rework_prevented"]["value"])
  with self.assertRaises(ValueError):ReworkValueService().calculate([],{"hours_per_defect":-1})
if __name__=="__main__":unittest.main()
