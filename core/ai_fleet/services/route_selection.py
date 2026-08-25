from decimal import Decimal
from typing import Any, Dict, List

from ..errors import DomainError
from ..routing import RoutingCandidate, RoutingRequest
from ..routing_strategies import RoutingStrategyService


class ExecutableRouteSelectionService:
    def __init__(self): self._strategies = RoutingStrategyService()

    def select(self, request: RoutingRequest, custom_weights: Dict[str, float] | None = None) -> Dict[str, Any]:
        request.validate()
        strategy = self._strategies.resolve(request.strategy, custom_weights)
        eligible: List[Dict[str, Any]] = []
        rejected = []
        for candidate in request.candidates:
            blockers = list(candidate.blockers)
            if not candidate.executable: blockers.append("not_preflight_executable")
            missing = [capability for capability in request.required_capabilities if capability not in candidate.capabilities or candidate.capabilities[capability].value is not True]
            blockers.extend(f"missing_capability:{item}" for item in missing)
            needed_context = request.estimated_input_tokens.value
            if needed_context is not None and candidate.context_capacity.value is not None and candidate.context_capacity.value < needed_context:
                blockers.append("context_capacity_insufficient")
            if blockers:
                rejected.append({"route_id": candidate.route_id, "blockers": sorted(set(blockers))})
                continue
            dimensions = {"quality": candidate.benchmark, "cost": candidate.estimated_cost, "speed": candidate.speed, "reliability": candidate.reliability}
            known = {}
            unknown = {}
            for name, evidence in dimensions.items():
                if evidence.value is None:
                    unknown[name] = evidence.reason or "unknown"
                    continue
                value = float(evidence.value)
                if name == "cost": value = float(Decimal("100") / (Decimal("1") + Decimal(str(value))))
                if not 0 <= value <= 100:
                    raise DomainError("validation_failed", message=f"Routing {name} evidence is outside its supported range.")
                known[name] = value
            weight_total = sum(strategy.weights[name] for name in known)
            score = sum(known[name] * strategy.weights[name] / weight_total for name in known) if weight_total else None
            eligible.append({"candidate": candidate, "score": score, "known_dimensions": known, "unknown_dimensions": unknown, "effective_weights": {name: strategy.weights[name] / weight_total for name in known} if weight_total else {}})
        if not eligible:
            raise DomainError("execution_unavailable", message="No preflight-executable route satisfies the task requirements.", details={"rejected": rejected})
        eligible.sort(key=lambda item: (item["score"] is None, -(item["score"] or 0), item["candidate"].route_id))
        winner = eligible[0]
        return {"selected_route": winner["candidate"].to_dict(), "score": round(winner["score"], 4) if winner["score"] is not None else None, "strategy": strategy.to_dict(), "known_dimensions": winner["known_dimensions"], "unknown_dimensions": winner["unknown_dimensions"], "effective_weights": winner["effective_weights"], "alternatives": [{"route_id": item["candidate"].route_id, "score": round(item["score"], 4) if item["score"] is not None else None, "unknown_dimensions": item["unknown_dimensions"]} for item in eligible[1:]], "rejected": rejected, "decision_basis": "preflight_executable_routes_only"}


executable_route_selection_service = ExecutableRouteSelectionService()
