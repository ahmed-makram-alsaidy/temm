import json
from typing import Any, Dict, List

from sqlalchemy import delete, func, select

from ..storage.database import AsyncSessionLocal
from ..storage.models import EventJournalRecord


class EventJournal:
    def __init__(self, retention_per_correlation: int = 1000):
        self.retention_per_correlation = retention_per_correlation

    async def append(self, event: Dict[str, Any]) -> int:
        async with AsyncSessionLocal() as session:
            record = EventJournalRecord(
                event_id=event["event_id"],
                correlation_id=event["correlation_id"],
                event_type=event["event_type"],
                causation_id=event.get("causation_id"),
                event_json=json.dumps(event),
            )
            session.add(record)
            await session.flush()
            sequence = record.sequence
            cutoff = (await session.execute(
                select(EventJournalRecord.sequence)
                .where(EventJournalRecord.correlation_id == record.correlation_id)
                .order_by(EventJournalRecord.sequence.desc())
                .offset(self.retention_per_correlation)
                .limit(1)
            )).scalar_one_or_none()
            if cutoff is not None:
                await session.execute(
                    delete(EventJournalRecord).where(
                        EventJournalRecord.correlation_id == record.correlation_id,
                        EventJournalRecord.sequence <= cutoff,
                    )
                )
            await session.commit()
            return sequence

    async def replay(self, correlation_id: str, after_sequence: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        bounded = min(max(limit, 1), 1000)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(EventJournalRecord)
                .where(
                    EventJournalRecord.correlation_id == correlation_id,
                    EventJournalRecord.sequence > max(after_sequence, 0),
                )
                .order_by(EventJournalRecord.sequence.asc())
                .limit(bounded)
            )).scalars().all()
        events = []
        for row in rows:
            payload = json.loads(row.event_json)
            payload["sequence"] = row.sequence
            events.append(payload)
        return events

    async def count(self, correlation_id: str) -> int:
        async with AsyncSessionLocal() as session:
            return int((await session.execute(
                select(func.count(EventJournalRecord.sequence)).where(EventJournalRecord.correlation_id == correlation_id)
            )).scalar_one())


event_journal = EventJournal()
