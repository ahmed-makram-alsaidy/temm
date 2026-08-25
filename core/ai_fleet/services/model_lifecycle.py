import json
import re
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ModelRecord
from .audit import audit_service


MODALITIES = {"text", "code", "vision", "image", "audio", "video", "embedding"}
SOURCE_TYPES = {"user", "catalog", "connector", "runtime"}


class ModelLifecycleService:
    async def create(self, session: AsyncSession, values: Dict[str, Any]) -> ModelRecord:
        model_id = values["id"].strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{1,127}", model_id):
            raise DomainError("validation_failed", message="Model id is invalid.")
        if await session.get(ModelRecord, model_id):
            raise DomainError("resource_conflict", message="Model id already exists.")
        modalities = self._modalities(values.get("modalities", ["text"]))
        source_type = values.get("source_type", "user")
        if source_type not in SOURCE_TYPES:
            raise DomainError("validation_failed", message="Model source type is invalid.")
        record = ModelRecord(
            id=model_id,
            name=values["name"].strip(),
            provider=values["provider"].strip().lower(),
            category=values.get("category", "general"),
            modalities=json.dumps(modalities),
            context_window=values.get("context_window"),
            is_local=values.get("is_local", False),
            is_active=values.get("is_active", True),
            registry_state="catalog",
            lifecycle_status="active",
            availability_state="unknown",
            availability_evidence="{}",
            source_type=source_type,
            source_uri=values.get("source_uri", ""),
            metadata_provenance="user_declared" if source_type == "user" else "unverified",
            pricing_provenance="unknown",
            capability_provenance="unknown",
            description=values.get("description", ""),
            revision=1,
        )
        session.add(record)
        await audit_service.append(session, action="model.created", resource_type="model", resource_id=model_id, details={"actor": "local_system", "source_type": source_type, "revision": record.revision})
        await session.commit()
        return record

    async def update(self, session: AsyncSession, model_id: str, changes: Dict[str, Any], expected_revision: int) -> ModelRecord:
        record = await self._get(session, model_id)
        if record.revision != expected_revision:
            raise DomainError("stale_revision", details={"current_revision": record.revision})
        if "modalities" in changes:
            record.modalities = json.dumps(self._modalities(changes["modalities"]))
        for field in ["name", "provider", "category", "context_window", "is_local", "is_active", "description", "source_uri"]:
            if field in changes:
                value = changes[field]
                if field in {"name", "provider"}:
                    value = value.strip()
                setattr(record, field, value)
        if "source_type" in changes:
            if changes["source_type"] not in SOURCE_TYPES:
                raise DomainError("validation_failed", message="Model source type is invalid.")
            record.source_type = changes["source_type"]
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="model.updated", resource_type="model", resource_id=model_id, details={"actor": "local_system", "fields": sorted(changes), "revision": record.revision})
        await session.commit()
        return record

    async def archive(self, session: AsyncSession, model_id: str) -> ModelRecord:
        record = await self._get(session, model_id)
        record.lifecycle_status = "archived"
        record.is_active = False
        record.availability_state = "unavailable"
        record.revision = (record.revision or 0) + 1
        await audit_service.append(session, action="model.archived", resource_type="model", resource_id=model_id, details={"actor": "local_system", "revision": record.revision})
        await session.commit()
        return record

    async def _get(self, session: AsyncSession, model_id: str) -> ModelRecord:
        record = await session.get(ModelRecord, model_id)
        if not record:
            raise DomainError("resource_not_found", message="Model was not found.")
        return record

    def _modalities(self, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(values))
        if not normalized or set(normalized) - MODALITIES:
            raise DomainError("validation_failed", message="One or more model modalities are invalid.")
        return normalized


model_lifecycle_service = ModelLifecycleService()
