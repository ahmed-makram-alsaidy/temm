from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import AuditRecord, ModelRecord


class ModelHistoryService:
    async def query(self, session: AsyncSession, model_id: str, since: datetime, until: datetime, after: int = 0, limit: int = 100, action: Optional[str] = None) -> List[Dict[str, Any]]:
        if not await session.get(ModelRecord, model_id):
            raise DomainError("resource_not_found", message="Model was not found.")
        if until <= since or until - since > timedelta(days=3660):
            raise DomainError("validation_failed", message="Model history range must be positive and at most ten years.")
        statement = select(AuditRecord).where(AuditRecord.resource_type == "model", AuditRecord.resource_id == model_id, AuditRecord.created_at >= since, AuditRecord.created_at < until, AuditRecord.sequence > max(after, 0))
        if action:
            if not action.startswith("model."):
                raise DomainError("validation_failed", message="Model history action is invalid.")
            statement = statement.where(AuditRecord.action == action)
        rows = (await session.execute(statement.order_by(AuditRecord.sequence).limit(min(max(limit, 1), 500)))).scalars().all()
        return [row.to_dict() for row in rows]


model_history_service = ModelHistoryService()
