from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EscalationPolicy:
    minimum_score: float
    minimum_confidence: Optional[float]
    max_attempts: int
    max_spend: str
    currency: str
    evaluator: str
    version: str = "1.0"

    def validate(self):
        if not 0 <= self.minimum_score <= 100 or self.minimum_confidence is not None and not 0 <= self.minimum_confidence <= 1 or not 1 <= self.max_attempts <= 20 or Decimal(self.max_spend) < 0 or len(self.currency) != 3 or not self.evaluator:
            raise ValueError("Escalation policy is invalid.")
        return self


class EscalationPolicyService:
    def decide(self, policy: EscalationPolicy, attempts_used: int, spend_used: str, evaluation: Optional[Dict[str, Any]], next_estimated_cost: Optional[str]) -> Dict[str, Any]:
        policy.validate()
        spend = Decimal(spend_used)
        maximum = Decimal(policy.max_spend)
        if attempts_used >= policy.max_attempts:
            return self._result("stop_attempts", policy, "maximum_attempts_reached")
        if evaluation is None:
            return self._result("require_evaluation", policy, "evaluation_missing")
        if evaluation.get("provenance") == "unknown" or evaluation.get("score") is None:
            return self._result("require_evaluation", policy, "evaluation_unknown")
        if evaluation.get("evaluator_type") != policy.evaluator:
            return self._result("require_evaluation", policy, "evaluator_mismatch")
        confidence = evaluation.get("confidence")
        score_passed = float(evaluation["score"]) >= policy.minimum_score
        confidence_passed = policy.minimum_confidence is None or confidence is not None and float(confidence) >= policy.minimum_confidence
        if score_passed and confidence_passed:
            return self._result("accept", policy, "thresholds_met", evaluation)
        if next_estimated_cost is None:
            return self._result("stop_budget", policy, "next_cost_unknown", evaluation)
        if spend + Decimal(next_estimated_cost) > maximum:
            return self._result("stop_budget", policy, "maximum_spend_would_be_exceeded", evaluation)
        return self._result("escalate", policy, "thresholds_not_met", evaluation)

    def _result(self, action: str, policy: EscalationPolicy, reason: str, evaluation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"action": action, "reason": reason, "policy": asdict(policy), "evaluation": evaluation, "decision_version": "1.0"}


escalation_policy_service = EscalationPolicyService()
