from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PROVENANCE = {"measured", "provider_reported", "estimated", "user_declared", "unknown"}


@dataclass(frozen=True)
class RoutingEvidence:
    value: Any
    provenance: str
    observed_at: Optional[str] = None
    source_id: Optional[str] = None
    reason: Optional[str] = None

    def validate(self) -> "RoutingEvidence":
        if self.provenance not in PROVENANCE:
            raise ValueError("Routing evidence provenance is invalid.")
        if self.value is None and self.provenance != "unknown":
            raise ValueError("Missing routing evidence must be unknown.")
        if self.value is not None and self.provenance == "unknown":
            raise ValueError("Unknown routing evidence cannot contain a value.")
        return self


@dataclass(frozen=True)
class RoutingCandidate:
    route_id: str
    agent_id: Optional[str]
    model_id: Optional[str]
    provider_instance_id: Optional[str]
    capabilities: Dict[str, RoutingEvidence]
    availability: RoutingEvidence
    benchmark: RoutingEvidence
    estimated_cost: RoutingEvidence
    speed: RoutingEvidence
    reliability: RoutingEvidence
    context_capacity: RoutingEvidence
    executable: bool
    blockers: List[str] = field(default_factory=list)

    def validate(self) -> "RoutingCandidate":
        if not self.route_id or not (self.agent_id or self.model_id) or self.agent_id and self.provider_instance_id or self.model_id and not self.provider_instance_id:
            raise ValueError("Routing candidate must identify either an Agent route or a Model+Provider route.")
        for evidence in [*self.capabilities.values(), self.availability, self.benchmark, self.estimated_cost, self.speed, self.reliability, self.context_capacity]:
            evidence.validate()
        if self.executable and self.blockers:
            raise ValueError("Executable routing candidate cannot have blockers.")
        return self

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class RoutingRequest:
    task_id: str
    category: str
    required_capabilities: List[str]
    estimated_input_tokens: RoutingEvidence
    strategy: str
    candidates: List[RoutingCandidate]

    def validate(self) -> "RoutingRequest":
        if not self.task_id or not self.category or not self.required_capabilities:
            raise ValueError("Routing request is incomplete.")
        self.estimated_input_tokens.validate()
        if not self.candidates:
            raise ValueError("Routing request requires candidates.")
        for candidate in self.candidates:
            candidate.validate()
        return self


def unknown_evidence(reason: str) -> RoutingEvidence:
    return RoutingEvidence(None, "unknown", reason=reason).validate()
