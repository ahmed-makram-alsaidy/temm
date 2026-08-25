from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .domain import CAPABILITIES


GATE_TYPES = {"approval", "evidence", "test", "security", "accessibility", "performance", "deployment", "backup"}
QUESTION_TYPES = {"text", "choice", "multi_choice", "boolean", "number"}


@dataclass(frozen=True)
class BlueprintCondition:
    capability: str
    equals: bool = True

    def validate(self):
        if self.capability not in CAPABILITIES: raise ValueError("Blueprint condition capability is unknown.")
        return self


@dataclass(frozen=True)
class BlueprintGate:
    gate_id: str
    gate_type: str
    required: bool
    description: str
    condition: Optional[BlueprintCondition] = None

    def validate(self):
        if not self.gate_id or self.gate_type not in GATE_TYPES or not self.description: raise ValueError("Blueprint gate is invalid.")
        if self.condition: self.condition.validate()
        return self


@dataclass(frozen=True)
class BlueprintQuestion:
    question_id: str
    text: str
    question_type: str
    required: bool
    options: List[str] = field(default_factory=list)
    condition: Optional[BlueprintCondition] = None

    def validate(self):
        if not self.question_id or not self.text or self.question_type not in QUESTION_TYPES or self.question_type in {"choice", "multi_choice"} and not self.options: raise ValueError("Blueprint question is invalid.")
        if self.condition: self.condition.validate()
        return self


@dataclass(frozen=True)
class BlueprintSection:
    section_id: str
    title: str
    requirement_types: List[str]
    gates: List[BlueprintGate] = field(default_factory=list)
    questions: List[BlueprintQuestion] = field(default_factory=list)
    condition: Optional[BlueprintCondition] = None

    def validate(self):
        if not self.section_id or not self.title or not self.requirement_types: raise ValueError("Blueprint section is invalid.")
        if self.condition: self.condition.validate()
        for gate in self.gates: gate.validate()
        for question in self.questions: question.validate()
        return self


@dataclass(frozen=True)
class BlueprintTemplate:
    template_id: str
    version: str
    project_type: str
    capabilities: List[str]
    sections: List[BlueprintSection]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self):
        if not self.template_id or not self.version or not self.project_type or not self.sections or len(set(self.capabilities)) != len(self.capabilities) or set(self.capabilities) - set(CAPABILITIES): raise ValueError("Blueprint template identity or capabilities are invalid.")
        ids = [section.section_id for section in self.sections]
        if len(set(ids)) != len(ids): raise ValueError("Blueprint section ids must be unique.")
        for section in self.sections: section.validate()
        return self

    def to_dict(self): self.validate(); return asdict(self)
