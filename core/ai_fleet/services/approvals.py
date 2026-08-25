import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..security import SensitiveDataRedactor
from ..storage.models import ApprovalRecord
from ..storage.secret_vault import secret_vault
from .audit import audit_service


ACTION_TYPES = {"command", "network", "paid_acquisition", "destructive", "elevated_permission", "quality", "spend", "missing_decision"}


class ApprovalService:
    async def request(
        self,
        session: AsyncSession,
        *,
        action_type: str,
        scope_type: str,
        scope_id: str,
        summary: str,
        details: Dict[str, Any],
        ttl_seconds: int = 900,
    ) -> ApprovalRecord:
        if action_type not in ACTION_TYPES:
            raise DomainError("validation_failed", message="Unsupported approval action type.")
        if not 30 <= ttl_seconds <= 86400:
            raise DomainError("validation_failed", message="Approval expiry must be between 30 seconds and 24 hours.")
        now = datetime.utcnow()
        record = ApprovalRecord(
            id=f"approval-{uuid.uuid4().hex[:12]}",
            action_type=action_type,
            scope_type=scope_type,
            scope_id=scope_id,
            summary=summary,
            details=json.dumps(SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact(details)),
            status="pending",
            requested_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        session.add(record)
        await audit_service.append(session, action="approval.requested", resource_type="approval", resource_id=record.id, details={"action_type": action_type, "scope_type": scope_type, "scope_id": scope_id})
        await session.commit()
        return record

    async def decide(self, session: AsyncSession, approval_id: str, approve: bool, reason: str = "") -> ApprovalRecord:
        record = await self._get(session, approval_id)
        self._expire(record)
        if record.status != "pending":
            raise DomainError("resource_conflict", message="Approval is no longer pending.")
        record.status = "approved" if approve else "rejected"
        record.decided_at = datetime.utcnow()
        record.decision_reason = reason
        await audit_service.append(session, action="approval.decided", resource_type="approval", resource_id=record.id, outcome=record.status, details={"approved": approve})
        await session.commit()
        return record

    async def consume(self, session: AsyncSession, approval_id: str, action_type: str, scope_type: str, scope_id: str) -> ApprovalRecord:
        record = await self._get(session, approval_id)
        self._expire(record)
        if record.status != "approved":
            raise DomainError("permission_denied", message="Approval is not valid.")
        if (record.action_type, record.scope_type, record.scope_id) != (action_type, scope_type, scope_id):
            raise DomainError("permission_denied", message="Approval scope does not match this action.")
        record.status = "consumed"
        record.consumed_at = datetime.utcnow()
        await audit_service.append(session, action="approval.consumed", resource_type="approval", resource_id=record.id, details={"action_type": action_type, "scope_type": scope_type, "scope_id": scope_id})
        await session.commit()
        return record

    async def list(self, session: AsyncSession, status: str | None = None) -> list[ApprovalRecord]:
        statement = select(ApprovalRecord).order_by(ApprovalRecord.requested_at.desc())
        if status:
            statement = statement.where(ApprovalRecord.status == status)
        records = (await session.execute(statement)).scalars().all()
        changed = False
        for record in records:
            changed = self._expire(record) or changed
        if changed:
            await session.commit()
        return records

    async def _get(self, session: AsyncSession, approval_id: str) -> ApprovalRecord:
        record = await session.get(ApprovalRecord, approval_id)
        if not record:
            raise DomainError("resource_not_found", message="Approval was not found.")
        return record

    def _expire(self, record: ApprovalRecord) -> bool:
        if record.status in {"pending", "approved"} and record.expires_at <= datetime.utcnow():
            record.status = "expired"
            return True
        return False


approval_service = ApprovalService()
