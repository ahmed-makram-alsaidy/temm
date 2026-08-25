from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


ERROR_SCHEMA_VERSION = "1.0"


class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    category: ErrorCategory
    status_code: int
    retryable: bool
    public_message: str


ERROR_DEFINITIONS: Dict[str, ErrorDefinition] = {}


def register_error(code: str, category: ErrorCategory, status_code: int, retryable: bool, public_message: str) -> ErrorDefinition:
    if code in ERROR_DEFINITIONS:
        raise ValueError(f"Duplicate error code: {code}")
    definition = ErrorDefinition(code, category, status_code, retryable, public_message)
    ERROR_DEFINITIONS[code] = definition
    return definition


register_error("validation_failed", ErrorCategory.VALIDATION, 422, False, "The request is invalid.")
register_error("resource_not_found", ErrorCategory.NOT_FOUND, 404, False, "The requested resource was not found.")
register_error("resource_conflict", ErrorCategory.CONFLICT, 409, False, "The request conflicts with current state.")
register_error("stale_revision", ErrorCategory.CONFLICT, 409, True, "The resource changed; reload and retry.")
register_error("authentication_unverified", ErrorCategory.AUTHENTICATION, 409, True, "Authentication has not been verified.")
register_error("permission_denied", ErrorCategory.AUTHORIZATION, 403, False, "Permission was denied.")
register_error("execution_unavailable", ErrorCategory.UNAVAILABLE, 409, True, "No verified execution route is currently available.")
register_error("host_capacity_unavailable", ErrorCategory.UNAVAILABLE, 409, True, "This machine cannot host a run right now.")
register_error("execution_timeout", ErrorCategory.TIMEOUT, 408, True, "Execution timed out.")
register_error("execution_cancelled", ErrorCategory.CANCELLED, 409, False, "Execution was cancelled.")
register_error("internal_error", ErrorCategory.INTERNAL, 500, True, "An internal error occurred.")


class DomainError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        retryable: Optional[bool] = None,
    ):
        definition = ERROR_DEFINITIONS.get(code)
        if definition is None and status_code is None:
            raise ValueError(f"Unknown error code: {code}")
        self.code = code
        self.category = definition.category if definition else ErrorCategory.INTERNAL
        self.status_code = status_code if status_code is not None else definition.status_code
        self.retryable = retryable if retryable is not None else (definition.retryable if definition else False)
        self.public_message = message or (definition.public_message if definition else "Request failed.")
        self.details = details or {}
        super().__init__(self.public_message)

    def payload(self) -> Dict[str, Any]:
        return {
            "schema_version": ERROR_SCHEMA_VERSION,
            "code": self.code,
            "category": self.category.value,
            "message": self.public_message,
            "retryable": self.retryable,
            "details": self.details,
        }
