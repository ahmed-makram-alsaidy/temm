import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Dict, Optional


DIMENSIONS = ("quality", "cost", "speed", "reliability")
BUILTINS = {
    "balanced": {"quality": 0.4, "cost": 0.3, "speed": 0.2, "reliability": 0.1},
    "economy": {"quality": 0.2, "cost": 0.6, "speed": 0.1, "reliability": 0.1},
    "quality": {"quality": 0.7, "cost": 0.05, "speed": 0.1, "reliability": 0.15},
    "fast": {"quality": 0.2, "cost": 0.1, "speed": 0.6, "reliability": 0.1},
}


@dataclass(frozen=True)
class RoutingStrategy:
    mode: str
    weights: Dict[str, float]
    version: str
    explanation: str

    def to_dict(self):
        return asdict(self)


class RoutingStrategyService:
    def resolve(self, mode: str, custom_weights: Optional[Dict[str, float]] = None) -> RoutingStrategy:
        if mode in BUILTINS:
            if custom_weights is not None:
                raise ValueError("Built-in strategies do not accept custom weights.")
            weights = dict(BUILTINS[mode])
        elif mode == "custom":
            if not isinstance(custom_weights, dict) or set(custom_weights) != set(DIMENSIONS):
                raise ValueError("Custom strategy requires all routing dimensions.")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1 for value in custom_weights.values()):
                raise ValueError("Custom strategy weights must be finite values from zero to one.")
            if abs(sum(Decimal(str(custom_weights[key])) for key in DIMENSIONS) - Decimal("1")) > Decimal("0.000001"):
                raise ValueError("Custom strategy weights must sum to one.")
            weights = {key: float(custom_weights[key]) for key in DIMENSIONS}
        else:
            raise ValueError("Routing strategy mode is invalid.")
        order = sorted(weights.items(), key=lambda item: (-item[1], DIMENSIONS.index(item[0])))
        explanation = ", ".join(f"{name} {weight * 100:.0f}%" for name, weight in order)
        return RoutingStrategy(mode, weights, "1.0", explanation)


routing_strategy_service = RoutingStrategyService()
