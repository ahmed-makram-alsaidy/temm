import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


EVENT_SCHEMA_VERSION = "1.0"
MAX_EVENT_PAYLOAD_BYTES = 256 * 1024
EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_type: str
    correlation_id: str
    causation_id: Optional[str]
    timestamp: str
    payload: Dict[str, Any]

    @classmethod
    def create(
        cls,
        event_type: str,
        correlation_id: str,
        payload: Dict[str, Any],
        causation_id: Optional[str] = None,
    ) -> "DomainEvent":
        if not EVENT_NAME_PATTERN.fullmatch(event_type):
            raise ValueError("Event type is invalid.")
        if not ID_PATTERN.fullmatch(correlation_id):
            raise ValueError("Correlation id is invalid.")
        if causation_id and not ID_PATTERN.fullmatch(causation_id):
            raise ValueError("Causation id is invalid.")
        encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError("Event payload exceeds 256 KiB.")
        return cls(
            event_id=f"evt-{uuid.uuid4().hex}",
            event_type=event_type,
            correlation_id=correlation_id,
            causation_id=causation_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
