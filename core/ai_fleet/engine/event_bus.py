"""In-memory typed event bus for live task execution streams."""

import asyncio
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Set

from ..events import DomainEvent
from ..security import SensitiveDataRedactor
from ..storage.secret_vault import secret_vault
from ..services.event_journal import event_journal


class TaskEventBus:
    def __init__(self):
        self._subscribers: DefaultDict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._history: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    async def publish(self, task_id: str, event_type: str, causation_id: Optional[str] = None, **data: Any) -> Dict[str, Any]:
        redactor = SensitiveDataRedactor.from_environment(secret_vault.redaction_values())
        payload = redactor.redact(data)
        domain_event = DomainEvent.create(
            event_type=f"task.{event_type}",
            correlation_id=task_id,
            causation_id=causation_id,
            payload=payload,
        )
        event = {
            **domain_event.to_dict(),
            "type": event_type,
            "task_id": task_id,
            **payload,
        }
        event["sequence"] = await event_journal.append(event)
        history = self._history[task_id]
        history.append(event)
        if len(history) > 120:
            del history[:-120]
        for queue in list(self._subscribers.get(task_id, set())):
            await queue.put(event)
        return event

    def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=240)
        for event in self._history.get(task_id, []):
            queue.put_nowait(event)
        self._subscribers[task_id].add(queue)
        return queue

    async def subscribe_persistent(self, task_id: str, after_sequence: int = 0) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1200)
        for event in await event_journal.replay(task_id, after_sequence=after_sequence):
            queue.put_nowait(event)
        self._subscribers[task_id].add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[task_id].discard(queue)
        if not self._subscribers[task_id]:
            self._subscribers.pop(task_id, None)


task_event_bus = TaskEventBus()
