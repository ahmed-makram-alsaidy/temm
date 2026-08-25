import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..security import SensitiveDataRedactor
from ..storage.models import AuditRecord
from ..storage.secret_vault import secret_vault


class AuditService:
    async def append(
        self,
        session: AsyncSession,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "success",
        details: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> AuditRecord:
        redacted = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact(details or {})
        record = AuditRecord(
            audit_id=f"audit-{uuid.uuid4().hex}",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=json.dumps(redacted),
            correlation_id=correlation_id,
        )
        session.add(record)
        await session.flush()
        return record

    async def query(
        self,
        session: AsyncSession,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> List[AuditRecord]:
        statement = select(AuditRecord).where(AuditRecord.sequence > max(after_sequence, 0))
        if action:
            statement = statement.where(AuditRecord.action == action)
        if resource_type:
            statement = statement.where(AuditRecord.resource_type == resource_type)
        if resource_id:
            statement = statement.where(AuditRecord.resource_id == resource_id)
        return (await session.execute(statement.order_by(AuditRecord.sequence.asc()).limit(min(max(limit, 1), 500)))).scalars().all()


audit_service = AuditService()
