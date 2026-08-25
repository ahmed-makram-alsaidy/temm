import unittest
from core.ai_fleet.services.completeness_audit import CompletenessAuditService
class CompletenessAuditTests(unittest.TestCase):
 def test_critical_blocker_cannot_be_hidden_by_other_passes(self):
  result=CompletenessAuditService().aggregate([{"findings":[{"rule":"secret","severity":"critical","evidence":{"file":"x"}}]},{"findings":[],"score":100}],[],[{"task_id":"t","done":True}]);self.assertFalse(result["ready"]);self.assertFalse(result["aggregate_score_override_allowed"]);self.assertEqual(result["blocking_findings"][0]["rule"],"secret")
 def test_incomplete_task_and_unknown_blocking_evidence_prevent_ready(self):
  result=CompletenessAuditService().aggregate([{"findings":[{"rule":"security","severity":"high","evidence":"unknown"}]}],[],[{"task_id":"t","done":False,"blockers":["criteria"]}]);self.assertFalse(result["ready"]);self.assertTrue(result["unknown_blocking_evidence"]);self.assertTrue(result["incomplete_tasks"])
 def test_resolved_blocker_allows_ready(self):
  result=CompletenessAuditService().aggregate([{"findings":[{"rule":"x","severity":"high","evidence":{},"status":"resolved"}]}],[],[{"done":True}]);self.assertTrue(result["ready"])
if __name__=="__main__":unittest.main()
