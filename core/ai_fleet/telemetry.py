from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MeasurementSource(str, Enum):
    MEASURED = "measured"
    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Measurement:
    value: Optional[float]
    source: MeasurementSource
    method: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "Measurement":
        if self.value is None and self.source != MeasurementSource.UNKNOWN:
            raise ValueError("Missing measurement values must use UNKNOWN provenance.")
        if self.source == MeasurementSource.ESTIMATED and not self.method:
            raise ValueError("Estimated measurements require a method.")
        return self


def estimated(value: float, method: str, **metadata: Any) -> Measurement:
    return Measurement(value, MeasurementSource.ESTIMATED, method, metadata).validate()


def unknown() -> Measurement:
    return Measurement(None, MeasurementSource.UNKNOWN).validate()
