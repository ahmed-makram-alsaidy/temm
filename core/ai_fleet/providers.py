from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, FrozenSet, List, Optional

from .errors import DomainError


PROVIDER_PROTOCOL_VERSION = "1.0"


class ProviderCapability(str, Enum):
    CONFIGURE = "configure"
    AUTH = "auth"
    HEALTH = "health"
    LIST_MODELS = "list_models"
    EXECUTE = "execute"
    STREAM = "stream"
    CANCEL = "cancel"
    USAGE = "usage"
    QUOTA = "quota"


class ProviderHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderHealthObservation:
    state: ProviderHealthState
    checked_at: datetime
    expires_at: datetime
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderModelObservation:
    model_id: str
    display_name: str
    modalities: List[str]
    observed_at: datetime
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderUsageObservation:
    checked_at: datetime
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    requests: Optional[int] = None
    source: str = "provider_reported"


@dataclass(frozen=True)
class ProviderQuotaObservation:
    checked_at: datetime
    scope: str
    limit: Optional[float] = None
    remaining: Optional[float] = None
    resets_at: Optional[datetime] = None
    unit: str = "unknown"


@dataclass(frozen=True)
class ProviderStreamEvent:
    event_type: str
    text: str = ""
    usage: Optional[ProviderUsageObservation] = None
    error_code: Optional[str] = None


class ProviderAdapter(ABC):
    adapter_id: str
    protocol_version: str = PROVIDER_PROTOCOL_VERSION
    capabilities: FrozenSet[ProviderCapability] = frozenset()

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    def require(self, capability: ProviderCapability) -> None:
        if not self.supports(capability):
            raise DomainError("execution_unavailable", message=f"Provider adapter does not support {capability.value}.")

    async def detect(self) -> bool:
        return False

    async def configure(self, configuration: Dict[str, Any]) -> None:
        self.require(ProviderCapability.CONFIGURE)

    async def auth_status(self) -> str:
        self.require(ProviderCapability.AUTH)
        return "unknown"

    async def health(self) -> ProviderHealthObservation:
        self.require(ProviderCapability.HEALTH)
        raise NotImplementedError

    async def list_models(self) -> List[ProviderModelObservation]:
        self.require(ProviderCapability.LIST_MODELS)
        return []

    async def execute(self, model_id: str, prompt: str, request_id: str) -> Dict[str, Any]:
        self.require(ProviderCapability.EXECUTE)
        raise NotImplementedError

    async def stream(self, model_id: str, prompt: str, request_id: str) -> AsyncIterator[ProviderStreamEvent]:
        self.require(ProviderCapability.STREAM)
        if False:
            yield ProviderStreamEvent("done")

    async def cancel(self, request_id: str) -> bool:
        self.require(ProviderCapability.CANCEL)
        return False

    async def usage(self) -> ProviderUsageObservation:
        self.require(ProviderCapability.USAGE)
        raise NotImplementedError

    async def quota(self) -> List[ProviderQuotaObservation]:
        self.require(ProviderCapability.QUOTA)
        return []


def validate_adapter(adapter: ProviderAdapter) -> None:
    if not adapter.adapter_id or not adapter.adapter_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Provider adapter id is invalid.")
    if adapter.protocol_version != PROVIDER_PROTOCOL_VERSION:
        raise ValueError("Provider protocol version is incompatible.")
    if ProviderCapability.STREAM in adapter.capabilities and ProviderCapability.EXECUTE not in adapter.capabilities:
        raise ValueError("Streaming providers must also declare execute capability.")
