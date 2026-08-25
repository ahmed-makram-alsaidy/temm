import re
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ModelFavoriteRecord, ModelRecord
from .audit import audit_service


class ModelFavoriteService:
    async def set(self, session: AsyncSession, model_id: str, use_case: str) -> ModelFavoriteRecord:
        normalized = use_case.strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", normalized):
            raise DomainError("validation_failed", message="Favorite use case is invalid.")
        model = await session.get(ModelRecord, model_id)
        if not model or model.lifecycle_status != "active":
            raise DomainError("resource_not_found", message="Active model was not found.")
        existing = (await session.execute(select(ModelFavoriteRecord).where(ModelFavoriteRecord.model_id == model_id, ModelFavoriteRecord.use_case == normalized))).scalar_one_or_none()
        if existing:
            return existing
        record = ModelFavoriteRecord(id=f"favorite-{uuid.uuid4().hex[:12]}", model_id=model_id, use_case=normalized, provenance="user_preference")
        session.add(record)
        await audit_service.append(session, action="model.favorite_set", resource_type="model", resource_id=model_id, details={"actor": "local_system", "use_case": normalized, "ranking_evidence": False})
        await session.commit()
        return record

    async def remove(self, session: AsyncSession, model_id: str, use_case: str) -> None:
        record = (await session.execute(select(ModelFavoriteRecord).where(ModelFavoriteRecord.model_id == model_id, ModelFavoriteRecord.use_case == use_case))).scalar_one_or_none()
        if not record:
            raise DomainError("resource_not_found", message="Model favorite was not found.")
        await session.delete(record)
        await audit_service.append(session, action="model.favorite_removed", resource_type="model", resource_id=model_id, details={"actor": "local_system", "use_case": use_case, "ranking_evidence": False})
        await session.commit()

    async def list(self, session: AsyncSession, use_case: Optional[str] = None) -> List[ModelFavoriteRecord]:
        statement = select(ModelFavoriteRecord)
        if use_case:
            statement = statement.where(ModelFavoriteRecord.use_case == use_case)
        return (await session.execute(statement.order_by(ModelFavoriteRecord.use_case, ModelFavoriteRecord.created_at))).scalars().all()


model_favorite_service = ModelFavoriteService()
