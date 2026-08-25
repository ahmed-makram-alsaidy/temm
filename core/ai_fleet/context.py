from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ContextSourceType(str, Enum):
    FILE = "file"
    REQUIREMENT = "requirement"
    DECISION = "decision"
    ASSET = "asset"
    RUN = "run"
    RESEARCH = "research"
    BLUEPRINT = "blueprint"
    NEED = "need"
    TASK = "task"


@dataclass(frozen=True)
class ContextSource:
    source_type: ContextSourceType
    source_id: str
    version: str
    provenance: str
    content_hash: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self):
        if not self.source_id or not self.version or self.provenance not in {"measured", "provider_reported", "user_declared", "owner_declared", "observed", "imported", "model_proposed", "unknown"}: raise ValueError("Context source identity or provenance is invalid.")
        if self.source_type == ContextSourceType.FILE and (not self.workspace_id or not self.content_hash): raise ValueError("File context requires workspace and content hash.")
        if self.content_hash is not None and (len(self.content_hash) != 64 or any(char not in "0123456789abcdef" for char in self.content_hash.lower())): raise ValueError("Context source hash is invalid.")
        return self

    def to_dict(self):
        payload = asdict(self); payload["source_type"] = self.source_type.value; return payload
