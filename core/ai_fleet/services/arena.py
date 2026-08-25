import secrets
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ArenaSessionRecord, TaskRun
from .run_output import run_output_service


class ArenaService:
    async def create(self, session: AsyncSession, run_a_id: str, run_b_id: str) -> Dict[str, Any]:
        if run_a_id == run_b_id:
            raise DomainError("validation_failed", message="Arena requires two distinct runs.")
        first = await session.get(TaskRun, run_a_id)
        second = await session.get(TaskRun, run_b_id)
        if not first or not second or first.status != "completed" or second.status != "completed":
            raise DomainError("resource_conflict", message="Arena requires two completed real runs.")
        if first.prompt != second.prompt:
            raise DomainError("validation_failed", message="Arena runs must use the same prompt.")
        if not (first.selected_agent_id or first.selected_model_id) or not (second.selected_agent_id or second.selected_model_id):
            raise DomainError("validation_failed", message="Arena runs require persisted executor identities.")
        label_a, label_b = (run_a_id, run_b_id) if secrets.randbelow(2) == 0 else (run_b_id, run_a_id)
        record = ArenaSessionRecord(id=f"arena-{uuid.uuid4().hex[:12]}", run_a_id=run_a_id, run_b_id=run_b_id, label_a_run_id=label_a, label_b_run_id=label_b, status="awaiting_vote")
        session.add(record)
        await session.commit()
        return await self._public(session, record)

    async def get(self, session: AsyncSession, arena_id: str) -> Dict[str, Any]:
        record = await session.get(ArenaSessionRecord, arena_id)
        if not record:
            raise DomainError("resource_not_found", message="Arena session was not found.")
        return await self._public(session, record) if record.status == "awaiting_vote" else await self._revealed(session, record)

    async def vote(self, session: AsyncSession, arena_id: str, winner: str) -> Dict[str, Any]:
        record = await session.get(ArenaSessionRecord, arena_id)
        if not record:
            raise DomainError("resource_not_found", message="Arena session was not found.")
        if record.status != "awaiting_vote":
            raise DomainError("resource_conflict", message="Arena vote was already submitted.")
        if winner not in {"a", "b", "tie"}:
            raise DomainError("validation_failed", message="Arena winner must be a, b, or tie.")
        record.winner_label = winner
        record.status = "voted"
        record.voted_at = datetime.utcnow()
        await session.commit()
        return await self._revealed(session, record)

    async def _public(self, session: AsyncSession, record: ArenaSessionRecord) -> Dict[str, Any]:
        return {"arena_id": record.id, "status": record.status, "response_a": await self._output(session, record.label_a_run_id), "response_b": await self._output(session, record.label_b_run_id), "identities_revealed": False}

    async def _revealed(self, session: AsyncSession, record: ArenaSessionRecord) -> Dict[str, Any]:
        run_a = await session.get(TaskRun, record.label_a_run_id)
        run_b = await session.get(TaskRun, record.label_b_run_id)
        return {"arena_id": record.id, "status": record.status, "winner": record.winner_label, "response_a": await self._output(session, record.label_a_run_id), "response_b": await self._output(session, record.label_b_run_id), "identity_a": {"run_id": run_a.id, "model_id": run_a.selected_model_id, "agent_id": run_a.selected_agent_id}, "identity_b": {"run_id": run_b.id, "model_id": run_b.selected_model_id, "agent_id": run_b.selected_agent_id}, "identities_revealed": True, "voted_at": record.voted_at.isoformat() if record.voted_at else None}

    async def _output(self, session: AsyncSession, run_id: str) -> str:
        chunks = await run_output_service.list(session, run_id, 0, 500)
        return "".join(chunk.content for chunk in chunks if chunk.stream in {"stdout", "output", "terminal"})


arena_service = ArenaService()
