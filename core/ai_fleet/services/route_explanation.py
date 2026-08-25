from typing import Any, Dict


class RouteExplanationService:
    def explain(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        route = decision["selected_route"]
        evidence = {"quality": route["benchmark"], "cost": route["estimated_cost"], "speed": route["speed"], "reliability": route["reliability"], "availability": route["availability"], "context": route["context_capacity"]}
        claims = []
        unknowns = []
        source_times = {}
        for name, item in evidence.items():
            if item["value"] is None:
                unknowns.append({"dimension": name, "reason": item.get("reason") or "unknown"})
                continue
            claims.append({"dimension": name, "value": item["value"], "provenance": item["provenance"], "source_id": item.get("source_id")})
            if item.get("observed_at"): source_times[name] = item["observed_at"]
        alternatives = []
        for item in decision.get("alternatives", []):
            comparison = None
            if decision.get("score") is not None and item.get("score") is not None:
                comparison = {"selected_score": decision["score"], "alternative_score": item["score"], "comparable": True}
            alternatives.append({"route_id": item["route_id"], "comparison": comparison, "unknown_dimensions": item.get("unknown_dimensions", {})})
        return {"selected_route_id": route["route_id"], "decision_basis": decision["decision_basis"], "strategy": decision["strategy"], "score": decision.get("score"), "claims": claims, "unknowns": unknowns, "effective_weights": decision.get("effective_weights", {}), "alternatives": alternatives, "rejected": decision.get("rejected", []), "source_times": source_times, "unsupported_comparative_claims": False}


route_explanation_service = RouteExplanationService()
