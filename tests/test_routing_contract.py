import unittest

from core.ai_fleet.routing import RoutingCandidate, RoutingEvidence, RoutingRequest, unknown_evidence


class RoutingInputContractTests(unittest.TestCase):
    def candidate(self):
        return RoutingCandidate(route_id="provider:model:provider", agent_id=None, model_id="model", provider_instance_id="provider", capabilities={"coding": RoutingEvidence(True, "provider_reported", observed_at="2026-01-01T00:00:00")}, availability=RoutingEvidence(True, "measured", observed_at="2026-01-01T00:00:00"), benchmark=unknown_evidence("no_comparable_benchmark"), estimated_cost=RoutingEvidence("0.25", "estimated", source_id="price-1"), speed=unknown_evidence("latency_sample_missing"), reliability=unknown_evidence("insufficient_attempts"), context_capacity=RoutingEvidence(128000, "provider_reported"), executable=True)

    def test_contract_preserves_unknowns_and_route_identity(self):
        candidate = self.candidate().validate()
        request = RoutingRequest("task-1", "coding", ["coding"], RoutingEvidence(1000, "estimated", reason="word_count_multiplier"), "balanced", [candidate]).validate()
        payload = candidate.to_dict()
        self.assertIsNone(payload["agent_id"])
        self.assertEqual(payload["model_id"], "model")
        self.assertEqual(payload["provider_instance_id"], "provider")
        self.assertIsNone(payload["benchmark"]["value"])
        self.assertEqual(payload["benchmark"]["reason"], "no_comparable_benchmark")
        self.assertEqual(request.estimated_input_tokens.provenance, "estimated")

    def test_invalid_unknown_and_executable_blockers_are_rejected(self):
        with self.assertRaises(ValueError): RoutingEvidence(10, "unknown").validate()
        with self.assertRaises(ValueError): RoutingEvidence(None, "measured").validate()
        values = self.candidate().__dict__ | {"blockers": ["auth_missing"]}
        with self.assertRaises(ValueError): RoutingCandidate(**values).validate()


if __name__ == "__main__":
    unittest.main()
