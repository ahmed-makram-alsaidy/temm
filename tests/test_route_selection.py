import unittest

from core.ai_fleet.routing import RoutingCandidate, RoutingEvidence, RoutingRequest, unknown_evidence
from core.ai_fleet.services.route_selection import ExecutableRouteSelectionService


class ExecutableRouteSelectionTests(unittest.TestCase):
    def candidate(self, route, quality, executable=True, blockers=None, context=10000, capabilities=None, speed=None):
        return RoutingCandidate(route, f"agent-{route}", None, None, {name: RoutingEvidence(True, "measured") for name in (capabilities or ["coding"])}, RoutingEvidence(True, "measured"), RoutingEvidence(quality, "measured") if quality is not None else unknown_evidence("benchmark_missing"), RoutingEvidence(1.0, "estimated"), RoutingEvidence(speed, "measured") if speed is not None else unknown_evidence("speed_missing"), RoutingEvidence(90, "measured"), RoutingEvidence(context, "provider_reported"), executable, blockers or [])

    def test_selects_only_preflight_executable_route(self):
        unavailable = self.candidate("best-catalog", 100, executable=False)
        ready = self.candidate("ready", 80)
        request = RoutingRequest("task", "coding", ["coding"], RoutingEvidence(1000, "estimated", reason="method"), "balanced", [unavailable, ready])
        result = ExecutableRouteSelectionService().select(request)
        self.assertEqual(result["selected_route"]["route_id"], "ready")
        self.assertEqual(result["decision_basis"], "preflight_executable_routes_only")
        self.assertEqual(result["rejected"][0]["blockers"], ["not_preflight_executable"])

    def test_unknown_dimensions_are_renormalized_not_zeroed(self):
        candidate = self.candidate("unknown-speed", 80, speed=None)
        request = RoutingRequest("task", "coding", ["coding"], RoutingEvidence(1000, "estimated", reason="method"), "balanced", [candidate])
        result = ExecutableRouteSelectionService().select(request)
        self.assertEqual(result["unknown_dimensions"]["speed"], "speed_missing")
        self.assertNotIn("speed", result["effective_weights"])
        self.assertAlmostEqual(sum(result["effective_weights"].values()), 1)
        self.assertGreater(result["score"], 0)

    def test_capability_and_context_blockers_prevent_selection(self):
        missing = self.candidate("missing", 90, capabilities=["research"])
        short = self.candidate("short", 90, context=100)
        request = RoutingRequest("task", "coding", ["coding"], RoutingEvidence(1000, "estimated", reason="method"), "balanced", [missing, short])
        with self.assertRaises(Exception) as context:
            ExecutableRouteSelectionService().select(request)
        rejected = context.exception.details["rejected"]
        self.assertTrue(any("missing_capability:coding" in item["blockers"] for item in rejected))
        self.assertTrue(any("context_capacity_insufficient" in item["blockers"] for item in rejected))


if __name__ == "__main__": unittest.main()
