from datetime import datetime, timedelta
from typing import Any, Dict, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from .audit import audit_service

from ..storage.models import ModelRecord


PROVIDER_ALIASES = {"gemini": "google", "claude": "anthropic"}
SUPPORTED_API_PROVIDERS = {"openai", "anthropic", "google", "groq", "deepseek", "bedrock"}


class ModelRegistryService:
    def canonical_provider(self, model: ModelRecord) -> str:
        value = (model.provider or "").lower()
        if "gemini" in model.id.lower():
            return "google"
        if "claude" in model.id.lower():
            return "anthropic"
        return PROVIDER_ALIASES.get(value, value)

    def assess(
        self,
        model: ModelRecord,
        configured: Dict[str, Dict[str, Any]],
        runtime_status: Dict[str, Any],
    ) -> Dict[str, Any]:
        provider = self.canonical_provider(model)
        if model.lifecycle_status != "active" or not model.is_active:
            return self._state("disabled", False, "registry_disabled", "Model is disabled in the registry.")
        if provider == "ollama" or model.is_local:
            if not runtime_status.get("running"):
                return self._state("catalog", False, "runtime_unavailable", "Local runtime is unavailable.")
            reported = {str(item.get("name") or "") for item in runtime_status.get("models", [])}
            candidates = {model.id, model.name, model.id.removeprefix("ollama-")}
            if not reported.intersection(candidates):
                return self._state("discovered", False, "model_not_reported", "Runtime is online but did not report this model identity.")
            return self._state("executable", True, "runtime_reported", "Runtime reported this model in the current observation.")
        if provider not in SUPPORTED_API_PROVIDERS:
            return self._state("catalog", False, "provider_adapter_missing", "No execution adapter is available for this provider.")
        provider_state = configured.get(provider, {})
        if not provider_state.get("is_configured"):
            return self._state("catalog", False, "provider_not_configured", "Provider credentials are not configured.")
        now = datetime.utcnow()
        if model.availability_state == "available" and model.availability_expires_at and model.availability_expires_at > now:
            return self._state("executable", True, "availability_observed", "Provider model availability is supported by a current observation.")
        if model.availability_expires_at and model.availability_expires_at <= now:
            return self._state("configured", False, "availability_stale", "The last availability observation has expired.")
        return self._state("configured", False, "availability_unverified", "Provider is configured, but current model availability has not been observed.")

    async def record_observation(
        self,
        session: AsyncSession,
        model_id: str,
        *,
        state: str,
        source: str,
        evidence: Dict[str, Any],
        ttl_seconds: int = 300,
    ) -> ModelRecord:
        if state not in {"available", "unavailable", "degraded"}:
            raise DomainError("validation_failed", message="Availability state is invalid.")
        if source not in {"provider", "runtime", "probe"}:
            raise DomainError("validation_failed", message="Availability source is invalid.")
        if not 10 <= ttl_seconds <= 86400:
            raise DomainError("validation_failed", message="Availability TTL is invalid.")
        record = await session.get(ModelRecord, model_id)
        if not record:
            raise DomainError("resource_not_found", message="Model was not found.")
        now = datetime.utcnow()
        record.availability_state = state
        record.availability_evidence = __import__("json").dumps({"source": source, **evidence})
        record.availability_checked_at = now
        record.availability_expires_at = now + timedelta(seconds=ttl_seconds)
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="model.availability_observed", resource_type="model", resource_id=model_id, outcome=state, details={"actor": "local_system", "source": source, "ttl_seconds": ttl_seconds, "revision": record.revision})
        await session.commit()
        return record

    def assess_many(self, models: Iterable[ModelRecord], configured: Dict[str, Dict[str, Any]], runtime_status: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {model.id: self.assess(model, configured, runtime_status) for model in models}

    def _state(self, state: str, executable: bool, code: str, detail: str) -> Dict[str, Any]:
        return {"state": state, "executable": executable, "code": code, "detail": detail}


model_registry_service = ModelRegistryService()
