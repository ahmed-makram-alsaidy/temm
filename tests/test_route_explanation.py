import unittest

from core.ai_fleet.routing import RoutingCandidate, RoutingEvidence, RoutingRequest, unknown_evidence
from core.ai_fleet.services.route_explanation import RouteExplanationService
from core.ai_fleet.services.route_selection import ExecutableRouteSelectionService


class RouteExplanationTests(unittest.TestCase):
    def test_explanation_contains_only_supported_claims_and_explicit_unknowns(self):
        candidate = RoutingCandidate("route", "agent", None, None, {"coding": RoutingEvidence(True, "measured")}, RoutingEvidence(True, "measured", observed_at="2026-01-01T00:00:00"), RoutingEvidence(90, "measured", observed_at="2026-01-02T00:00:00", source_id="suite-1"), RoutingEvidence("0.2", "estimated", source_id="price-1"), unknown_evidence("speed_sample_missing"), RoutingEvidence(98, "measured", observed_at="2026-01-03T00:00:00"), RoutingEvidence(10000, "provider_reported"), True)
        request = RoutingRequest("task", "coding", ["coding"], RoutingEvidence(1000, "estimated", reason="method"), "balanced", [candidate])
        decision = ExecutableRouteSelectionService().select(request)
        result = RouteExplanationService().explain(decision)
        self.assertFalse(result["unsupported_comparative_claims"])
        self.assertEqual({item["dimension"] for item in result["claims"]}, {"quality", "cost", "reliability", "availability", "context"})
        self.assertEqual(result["unknowns"], [{"dimension": "speed", "reason": "speed_sample_missing"}])
        self.assertEqual(result["source_times"]["quality"], "2026-01-02T00:00:00")
        self.assertEqual(result["claims"][0]["provenance"], "measured")

    def test_incomparable_alternative_has_no_score_claim(self):
        decision = {"selected_route": {"route_id": "a", "benchmark": {"value": None, "provenance": "unknown", "reason": "none"}, "estimated_cost": {"value": None, "provenance": "unknown"}, "speed": {"value": None, "provenance": "unknown"}, "reliability": {"value": None, "provenance": "unknown"}, "availability": {"value": True, "provenance": "measured"}, "context_capacity": {"value": None, "provenance": "unknown"}}, "decision_basis": "preflight_executable_routes_only", "strategy": {}, "score": None, "alternatives": [{"route_id": "b", "score": None, "unknown_dimensions": {"quality": "unknown"}}], "rejected": []}
        result = RouteExplanationService().explain(decision)
        self.assertIsNone(result["alternatives"][0]["comparison"])


if __name__ == "__main__": unittest.main()
