import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..security import SensitiveDataRedactor
from ..storage.models import RunOutputChunkRecord
from ..storage.secret_vault import secret_vault


MAX_CHUNK_BYTES = 64 * 1024
MAX_RUN_OUTPUT_BYTES = 10 * 1024 * 1024


class RunOutputService:
    async def append(self, session: AsyncSession, run_id: str, stream: str, content: str, attempt_id: Optional[str] = None) -> RunOutputChunkRecord:
        redacted = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact_text(content)
        encoded = redacted.encode("utf-8")
        current = int((await session.execute(select(func.coalesce(func.sum(RunOutputChunkRecord.byte_count), 0)).where(RunOutputChunkRecord.run_id == run_id))).scalar_one())
        remaining = max(0, MAX_RUN_OUTPUT_BYTES - current)
        allowed = min(MAX_CHUNK_BYTES, remaining)
        truncated = len(encoded) > allowed
        stored_bytes = encoded[:allowed]
        while True:
            try:
                stored = stored_bytes.decode("utf-8")
                break
            except UnicodeDecodeError:
                stored_bytes = stored_bytes[:-1]
        sequence = int((await session.execute(select(func.count(RunOutputChunkRecord.id)).where(RunOutputChunkRecord.run_id == run_id))).scalar_one()) + 1
        record = RunOutputChunkRecord(
            id=f"output-{uuid.uuid4().hex[:12]}", run_id=run_id, attempt_id=attempt_id,
            sequence=sequence, stream=stream, content=stored, byte_count=len(stored_bytes), truncated=truncated,
        )
        session.add(record)
        await session.flush()
        return record

    async def append_many(self, session: AsyncSession, run_id: str, chunks: List[Dict[str, str]], attempt_id: Optional[str] = None) -> List[RunOutputChunkRecord]:
        records = []
        for chunk in chunks:
            record = await self.append(session, run_id, chunk["stream"], chunk["content"], attempt_id)
            records.append(record)
            if record.truncated or sum(item.byte_count for item in records) >= MAX_RUN_OUTPUT_BYTES:
                break
        return records

    async def list(self, session: AsyncSession, run_id: str, after_sequence: int = 0, limit: int = 200) -> List[RunOutputChunkRecord]:
        return (await session.execute(
            select(RunOutputChunkRecord)
            .where(RunOutputChunkRecord.run_id == run_id, RunOutputChunkRecord.sequence > max(after_sequence, 0))
            .order_by(RunOutputChunkRecord.sequence.asc())
            .limit(min(max(limit, 1), 500))
        )).scalars().all()


run_output_service = RunOutputService()
