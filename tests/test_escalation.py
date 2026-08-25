import unittest

from core.ai_fleet.services.escalation import EscalationPolicy, EscalationPolicyService


class EscalationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.service = EscalationPolicyService()
        self.policy = EscalationPolicy(90, 0.7, 3, "1.00", "USD", "model")

    def evaluation(self, score=80, confidence=0.8): return {"evaluator_type": "model", "score": score, "confidence": confidence, "provenance": "model_opinion"}

    def test_accepts_only_when_explicit_thresholds_met(self):
        result = self.service.decide(self.policy, 1, "0.10", self.evaluation(95, 0.8), "0.20")
        self.assertEqual(result["action"], "accept")
        self.assertEqual(result["reason"], "thresholds_met")

    def test_escalates_within_attempt_and_spend_limits(self):
        result = self.service.decide(self.policy, 1, "0.10", self.evaluation(80, 0.8), "0.20")
        self.assertEqual(result["action"], "escalate")
        self.assertEqual(result["decision_version"], "1.0")

    def test_missing_evaluation_or_cost_does_not_invent_confidence(self):
        self.assertEqual(self.service.decide(self.policy, 0, "0", None, "0.1")["action"], "require_evaluation")
        result = self.service.decide(self.policy, 1, "0.1", self.evaluation(80), None)
        self.assertEqual(result["action"], "stop_budget")
        self.assertEqual(result["reason"], "next_cost_unknown")

    def test_limits_stop_escalation(self):
        self.assertEqual(self.service.decide(self.policy, 3, "0.1", self.evaluation(), "0.1")["action"], "stop_attempts")
        result = self.service.decide(self.policy, 1, "0.90", self.evaluation(), "0.20")
        self.assertEqual(result["action"], "stop_budget")
        self.assertEqual(result["reason"], "maximum_spend_would_be_exceeded")

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError): self.service.decide(EscalationPolicy(101, None, 0, "-1", "US", ""), 0, "0", None, None)


if __name__ == "__main__": unittest.main()
