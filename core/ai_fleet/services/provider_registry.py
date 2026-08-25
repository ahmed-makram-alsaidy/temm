import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..providers import PROVIDER_PROTOCOL_VERSION, ProviderCapability
from ..security import SensitiveDataRedactor
from ..storage.models import ModelRecord, ProviderInstanceRecord
from ..storage.secret_vault import SecretVault, secret_vault
from .audit import audit_service


SENSITIVE_CONFIG_MARKERS = {"secret", "token", "password", "api_key", "apikey", "credential", "authorization"}


class ProviderRegistryService:
    def __init__(self, vault: SecretVault):
        self._vault = vault

    async def create(self, session: AsyncSession, values: Dict[str, Any]) -> ProviderInstanceRecord:
        instance_id = values.get("id") or f"provider-{uuid.uuid4().hex[:12]}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{1,63}", instance_id):
            raise DomainError("validation_failed", message="Provider instance id is invalid.")
        if await session.get(ProviderInstanceRecord, instance_id):
            raise DomainError("resource_conflict", message="Provider instance id already exists.")
        capabilities = self._capabilities(values.get("capabilities", []))
        configuration = self._configuration(values.get("configuration", {}))
        record = ProviderInstanceRecord(
            id=instance_id,
            name=values["name"].strip(),
            adapter_id=values["adapter_id"].strip(),
            protocol_version=PROVIDER_PROTOCOL_VERSION,
            capabilities=json.dumps(capabilities),
            configuration=json.dumps(configuration),
            lifecycle_status="active",
            user_enabled=True,
            health_state="unknown",
            health_evidence="{}",
            revision=1,
        )
        session.add(record)
        await audit_service.append(session, action="provider.created", resource_type="provider", resource_id=instance_id, details={"adapter_id": record.adapter_id, "capabilities": capabilities})
        await session.commit()
        return record

    async def update(self, session: AsyncSession, instance_id: str, changes: Dict[str, Any], expected_revision: int) -> ProviderInstanceRecord:
        record = await self._get(session, instance_id)
        if record.revision != expected_revision:
            raise DomainError("stale_revision", details={"current_revision": record.revision})
        if "name" in changes:
            record.name = changes["name"].strip()
        if "capabilities" in changes:
            record.capabilities = json.dumps(self._capabilities(changes["capabilities"]))
        if "configuration" in changes:
            record.configuration = json.dumps(self._configuration(changes["configuration"]))
        if "user_enabled" in changes:
            record.user_enabled = changes["user_enabled"]
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.updated", resource_type="provider", resource_id=instance_id, details={"fields": sorted(changes)})
        await session.commit()
        return record

    async def remove(self, session: AsyncSession, instance_id: str) -> Dict[str, Any]:
        record = await self._get(session, instance_id)
        self._delete_secrets(record)
        record.lifecycle_status = "archived"
        record.user_enabled = False
        record.health_state = "unknown"
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.archived", resource_type="provider", resource_id=instance_id)
        await session.commit()
        return {"provider_id": instance_id, "archived": True, "secrets_removed": True}

    async def record_health(self, session: AsyncSession, instance_id: str, state: str, evidence: Dict[str, Any], ttl_seconds: int = 60) -> ProviderInstanceRecord:
        record = await self._get(session, instance_id)
        if state not in {"healthy", "degraded", "rate_limited", "unavailable", "auth_failed", "unknown"}:
            raise DomainError("validation_failed", message="Provider health state is invalid.")
        if not 10 <= ttl_seconds <= 3600:
            raise DomainError("validation_failed", message="Provider health TTL is invalid.")
        now = datetime.utcnow()
        redacted = SensitiveDataRedactor.from_environment(self._vault.redaction_values()).redact(evidence)
        record.health_state = state
        record.health_evidence = json.dumps(redacted)
        record.health_checked_at = now
        record.health_expires_at = now + timedelta(seconds=ttl_seconds)
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.health_observed", resource_type="provider", resource_id=instance_id, outcome=state, details={"ttl_seconds": ttl_seconds})
        await session.commit()
        return record

    def assess_health(self, record: ProviderInstanceRecord, at: Optional[datetime] = None) -> Dict[str, Any]:
        at = at or datetime.utcnow()
        if record.lifecycle_status != "active" or not record.user_enabled:
            return {"state": "disabled", "usable": False, "reason": "provider_disabled"}
        if not record.health_expires_at or record.health_expires_at <= at:
            return {"state": "unknown", "usable": False, "reason": "health_stale_or_missing"}
        return {"state": record.health_state, "usable": record.health_state in {"healthy", "degraded"}, "reason": "current_observation"}

    async def ingest_models(self, session: AsyncSession, instance_id: str, observations: List[Dict[str, Any]], ttl_seconds: int = 300) -> List[ModelRecord]:
        provider = await self._get(session, instance_id)
        if not 10 <= ttl_seconds <= 86400:
            raise DomainError("validation_failed", message="Model observation TTL is invalid.")
        if "list_models" not in self._list(provider.capabilities):
            raise DomainError("permission_denied", message="Provider instance does not declare model-listing capability.")
        now = datetime.utcnow()
        expires = now + timedelta(seconds=ttl_seconds)
        observed_ids = set()
        records = []
        for observation in observations:
            raw_id = str(observation.get("model_id") or "").strip()
            if not raw_id or len(raw_id) > 128:
                raise DomainError("validation_failed", message="Provider model observation id is invalid.")
            model_id = f"{instance_id}:{raw_id}".lower()
            observed_ids.add(model_id)
            record = await session.get(ModelRecord, model_id)
            if not record:
                record = ModelRecord(id=model_id, name=str(observation.get("display_name") or raw_id)[:128], provider=instance_id)
                session.add(record)
            record.name = str(observation.get("display_name") or raw_id)[:128]
            record.modalities = json.dumps(list(dict.fromkeys(observation.get("modalities") or ["text"])))
            record.registry_state = "configured"
            record.lifecycle_status = "active"
            record.is_active = True
            record.availability_state = "available"
            record.availability_evidence = json.dumps({"source": "provider_list_models", "provider_instance_id": instance_id, "provider_model_id": raw_id})
            record.availability_checked_at = now
            record.availability_expires_at = expires
            record.source_type = "connector"
            record.source_uri = f"provider:{instance_id}"
            record.source_checked_at = now
            record.metadata_provenance = "provider_reported"
            record.capability_provenance = "unknown"
            record.pricing_provenance = "unknown"
            record.revision = (record.revision or 0) + 1
            records.append(record)
        existing = (await session.execute(select(ModelRecord).where(ModelRecord.source_uri == f"provider:{instance_id}"))).scalars().all()
        for record in existing:
            if record.id not in observed_ids:
                record.availability_state = "unavailable"
                record.availability_evidence = json.dumps({"source": "provider_list_models", "reason": "not_in_latest_observation", "provider_instance_id": instance_id})
                record.availability_checked_at = now
                record.availability_expires_at = expires
                record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.models_ingested", resource_type="provider", resource_id=instance_id, details={"observed_count": len(records), "ttl_seconds": ttl_seconds})
        await session.commit()
        return records

    async def list(self, session: AsyncSession) -> List[ProviderInstanceRecord]:
        return (await session.execute(select(ProviderInstanceRecord).order_by(ProviderInstanceRecord.name.asc()))).scalars().all()

    async def list_secrets(self, session: AsyncSession, instance_id: str) -> List[Dict[str, Any]]:
        record = await self._get(session, instance_id)
        return [{"reference": item, "configured": self._vault.has_key(self._secret_key(instance_id, item))} for item in self._list(record.secret_refs)]

    async def set_secret(self, session: AsyncSession, instance_id: str, reference: str, value: str) -> Dict[str, Any]:
        record = await self._get(session, instance_id)
        normalized = reference.strip().upper()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", normalized):
            raise DomainError("validation_failed", message="Provider secret reference is invalid.")
        self._vault.set_key(self._secret_key(instance_id, normalized), value)
        refs = self._list(record.secret_refs)
        if normalized not in refs:
            refs.append(normalized)
            record.secret_refs = json.dumps(refs)
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.secret_configured", resource_type="provider", resource_id=instance_id, details={"reference": normalized})
        await session.commit()
        return {"provider_id": instance_id, "reference": normalized, "configured": True, "revision": record.revision}

    async def delete_secret(self, session: AsyncSession, instance_id: str, reference: str) -> Dict[str, Any]:
        record = await self._get(session, instance_id)
        normalized = reference.strip().upper()
        refs = self._list(record.secret_refs)
        if normalized not in refs:
            raise DomainError("resource_not_found", message="Provider secret reference was not found.")
        self._vault.delete_key(self._secret_key(instance_id, normalized))
        refs.remove(normalized)
        record.secret_refs = json.dumps(refs)
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="provider.secret_removed", resource_type="provider", resource_id=instance_id, details={"reference": normalized})
        await session.commit()
        return {"provider_id": instance_id, "reference": normalized, "configured": False, "revision": record.revision}

    async def _get(self, session: AsyncSession, instance_id: str) -> ProviderInstanceRecord:
        record = await session.get(ProviderInstanceRecord, instance_id)
        if not record:
            raise DomainError("resource_not_found", message="Provider instance was not found.")
        return record

    def _capabilities(self, values: List[str]) -> List[str]:
        allowed = {item.value for item in ProviderCapability}
        normalized = list(dict.fromkeys(values))
        if set(normalized) - allowed:
            raise DomainError("validation_failed", message="Provider capabilities are invalid.")
        if "stream" in normalized and "execute" not in normalized:
            raise DomainError("validation_failed", message="Streaming providers must declare execute capability.")
        return normalized

    def _configuration(self, values: Dict[str, Any]) -> Dict[str, Any]:
        if len(values) > 50:
            raise DomainError("validation_failed", message="Provider configuration has too many fields.")
        for key, value in values.items():
            lowered = key.lower()
            if any(marker in lowered for marker in SENSITIVE_CONFIG_MARKERS):
                raise DomainError("validation_failed", message="Secrets must use encrypted secret references, not provider configuration.")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", key):
                raise DomainError("validation_failed", message="Provider configuration key is invalid.")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise DomainError("validation_failed", message="Provider configuration values must be scalar.")
        return values

    def _delete_secrets(self, record: ProviderInstanceRecord) -> None:
        for reference in self._list(record.secret_refs):
            self._vault.delete_key(self._secret_key(record.id, reference))
        record.secret_refs = "[]"

    def _secret_key(self, instance_id: str, reference: str) -> str:
        return f"provider:{instance_id}:{reference.lower()}"

    def _list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []


provider_registry_service = ProviderRegistryService(secret_vault)
