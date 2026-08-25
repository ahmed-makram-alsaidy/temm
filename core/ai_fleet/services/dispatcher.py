import asyncio
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List

from ..errors import DomainError


Dispatch = Callable[[str], Awaitable[Dict[str, Any]]]


class DispatcherService:
    async def dispatch(self, ready_task_ids: List[str], dispatch: Dispatch, concurrency: int, max_spend: str, estimated_costs: Dict[str, str | None], control: Dict[str, bool]) -> Dict[str, Any]:
        if not 1 <= concurrency <= 32 or Decimal(max_spend) < 0:
            raise DomainError("validation_failed", message="Dispatcher limits are invalid.")
        semaphore = asyncio.Semaphore(concurrency)
        launched = []
        skipped = []
        reserved = Decimal("0")
        coroutines = []

        async def run(task_id):
            async with semaphore:
                return task_id, await dispatch(task_id)

        for task_id in ready_task_ids:
            if control.get("cancelled"):
                skipped.append({"task_id": task_id, "reason": "orchestration_cancelled"})
                continue
            if control.get("paused"):
                skipped.append({"task_id": task_id, "reason": "orchestration_paused"})
                continue
            estimate = estimated_costs.get(task_id)
            if estimate is None:
                skipped.append({"task_id": task_id, "reason": "estimated_cost_unknown"})
                continue
            amount = Decimal(estimate)
            if reserved + amount > Decimal(max_spend):
                skipped.append({"task_id": task_id, "reason": "budget_limit"})
                continue
            reserved += amount
            launched.append(task_id)
            coroutines.append(run(task_id))
        results = await asyncio.gather(*coroutines) if coroutines else []
        return {"launched": launched, "results": [{"task_id": task_id, **result} for task_id, result in results], "skipped": skipped, "reserved_spend": str(reserved), "max_spend": str(Decimal(max_spend)), "concurrency": concurrency}


dispatcher_service = DispatcherService()
