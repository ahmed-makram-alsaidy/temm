import unittest
from core.ai_fleet.services.workflow_policy import WorkflowPolicyService
class WorkflowPolicyTests(unittest.TestCase):
 def test_conditions_are_deterministic(self):
  service=WorkflowPolicyService();self.assertTrue(service.condition({"operator":"equals","field":"status","value":"ok"},{"status":"ok"}));self.assertTrue(service.condition({"operator":"in","field":"code","values":[1,2]},{"code":2}));self.assertFalse(service.condition({"operator":"exists","field":"x","value":True},{}))
 def test_retry_is_bounded_with_backoff_and_terminal_failure(self):
  p={"max_attempts":3,"retryable_errors":["temporary"],"backoff_seconds":2,"max_backoff_seconds":3};one=WorkflowPolicyService().retry(1,"temporary",p);two=WorkflowPolicyService().retry(2,"temporary",p);three=WorkflowPolicyService().retry(3,"temporary",p);fatal=WorkflowPolicyService().retry(1,"auth",p);self.assertEqual([one["backoff_seconds"],two["backoff_seconds"]],[2,3]);self.assertEqual(three["decision"],"terminal");self.assertEqual(fatal["decision"],"terminal")
if __name__=="__main__":unittest.main()
