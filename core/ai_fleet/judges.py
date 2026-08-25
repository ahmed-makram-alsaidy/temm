from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JudgeType(str, Enum):
    MODEL = "model"
    RULE = "rule"
    TEST = "test"
    HUMAN = "human"


class JudgeProvenance(str, Enum):
    MODEL_OPINION = "model_opinion"
    DETERMINISTIC_RULE = "deterministic_rule"
    EXECUTED_TEST = "executed_test"
    HUMAN_PREFERENCE = "human_preference"


@dataclass(frozen=True)
class BlindCandidate:
    candidate_id: str
    content: str

    def validate(self) -> "BlindCandidate":
        if not self.candidate_id or len(self.candidate_id) > 64 or not self.content or len(self.content) > 2_000_000:
            raise ValueError("Blind candidate is invalid.")
        return self


@dataclass(frozen=True)
class JudgeRequest:
    request_id: str
    judge_type: JudgeType
    criteria: List[str]
    candidates: List[BlindCandidate]
    context: str = ""
    private_identity_map: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def validate(self) -> "JudgeRequest":
        if not self.request_id or not 1 <= len(self.criteria) <= 50 or not 1 <= len(self.candidates) <= 20 or len(self.context) > 100_000:
            raise ValueError("Judge request is invalid.")
        if len({candidate.candidate_id for candidate in self.candidates}) != len(self.candidates):
            raise ValueError("Blind candidate ids must be unique.")
        if set(self.private_identity_map) - {candidate.candidate_id for candidate in self.candidates}:
            raise ValueError("Private identity map references an unknown candidate.")
        for candidate in self.candidates:
            candidate.validate()
        return self

    def public_payload(self) -> Dict[str, Any]:
        self.validate()
        return {"request_id": self.request_id, "judge_type": self.judge_type.value, "criteria": self.criteria, "candidates": [asdict(candidate) for candidate in self.candidates], "context": self.context}


@dataclass(frozen=True)
class JudgeResult:
    request_id: str
    judge_type: JudgeType
    provenance: JudgeProvenance
    winner_candidate_id: Optional[str]
    scores: Dict[str, float]
    rationale: str
    confidence: Optional[float]
    method: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def validate(self, candidate_ids: List[str]) -> "JudgeResult":
        allowed = set(candidate_ids)
        if self.winner_candidate_id is not None and self.winner_candidate_id not in allowed:
            raise ValueError("Judge winner is not a candidate.")
        if set(self.scores) - allowed or any(not 0 <= score <= 100 for score in self.scores.values()):
            raise ValueError("Judge scores are invalid.")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Judge confidence is invalid.")
        if not self.rationale or len(self.rationale) > 100_000 or not self.method:
            raise ValueError("Judge rationale and method are required.")
        expected = {JudgeType.MODEL: JudgeProvenance.MODEL_OPINION, JudgeType.RULE: JudgeProvenance.DETERMINISTIC_RULE, JudgeType.TEST: JudgeProvenance.EXECUTED_TEST, JudgeType.HUMAN: JudgeProvenance.HUMAN_PREFERENCE}
        if self.provenance != expected[self.judge_type]:
            raise ValueError("Judge provenance is incompatible with judge type.")
        return self

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["judge_type"] = self.judge_type.value
        payload["provenance"] = self.provenance.value
        payload["ground_truth"] = False
        return payload
