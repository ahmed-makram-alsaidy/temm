import os
import re
from typing import Any, Iterable


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization", "key_value", "credential"}
PATTERNS = [
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"\b(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]


class SensitiveDataRedactor:
    def __init__(self, values: Iterable[str] = ()): 
        self._values = {value for value in values if isinstance(value, str) and len(value) >= 6}

    @classmethod
    def from_environment(cls, extra_values: Iterable[str] = ()) -> "SensitiveDataRedactor":
        values = list(extra_values)
        for name, value in os.environ.items():
            upper = name.upper()
            if any(marker in upper for marker in ["API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"]):
                values.append(value)
        return cls(values)

    def redact_text(self, value: str) -> str:
        result = value
        for secret in sorted(self._values, key=len, reverse=True):
            result = result.replace(secret, REDACTED)
        for pattern in PATTERNS:
            result = pattern.sub(REDACTED, result)
        return result

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                key: REDACTED if str(key).lower() in SENSITIVE_KEYS else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value
