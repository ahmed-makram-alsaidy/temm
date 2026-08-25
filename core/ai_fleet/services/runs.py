import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..engine.event_bus import task_event_bus
from ..errors import DomainError
from ..storage.models import RunAttemptRecord, TaskRun


TERMINAL_STATES = {"completed", "failed", "timed_out", "cancelled", "interrupted"}
TRANSITIONS = {
    "created": {"running", "cancelled", "failed"},
    "running": {"cancellation_requested", "completed", "failed", "timed_out", "cancelled", "interrupted"},
    "cancellation_requested": {"cancelled", "failed", "timed_out"},
}


class RunLifecycleService:
    async def create(self, session: AsyncSession, *, run_id: str, prompt: str, routing_mode: str, workspace_id: Optional[str] = None, project_id: Optional[str] = None, workflow_id: Optional[str] = None) -> TaskRun:
        if await session.get(TaskRun, run_id):
            raise DomainError("resource_conflict", message="Run id already exists.")
        run = TaskRun(id=run_id, prompt=prompt, routing_mode=routing_mode, workspace_id=workspace_id, project_id=project_id, workflow_id=workflow_id, status="created", revision=1)
        session.add(run)
        await session.commit()
        await task_event_bus.publish(run_id, "created", run_id=run_id)
        return run

    async def start(self, session: AsyncSession, run_id: str) -> TaskRun:
        run = await self._get(session, run_id)
        await self._transition(session, run, "running")
        run.started_at = run.started_at or datetime.utcnow()
        await session.commit()
        await task_event_bus.publish(run_id, "started", run_id=run_id)
        return run

    async def start_attempt(self, session: AsyncSession, run_id: str, executor_type: str, agent_id: Optional[str] = None, model_id: Optional[str] = None, provider_instance_id: Optional[str] = None) -> RunAttemptRecord:
        run = await self._get(session, run_id)
        if run.status != "running":
            raise DomainError("resource_conflict", message="Attempts can only start while a run is running.")
        number = int((await session.execute(select(func.count(RunAttemptRecord.id)).where(RunAttemptRecord.run_id == run_id))).scalar_one()) + 1
        attempt = RunAttemptRecord(id=f"attempt-{uuid.uuid4().hex[:12]}", run_id=run_id, attempt_number=number, executor_type=executor_type, agent_id=agent_id, model_id=model_id, provider_instance_id=provider_instance_id, status="running")
        session.add(attempt)
        run.current_attempt_id = attempt.id
        run.revision = (run.revision or 0) + 1
        await session.commit()
        await task_event_bus.publish(run_id, "attempt_started", attempt_id=attempt.id, attempt_number=number)
        return attempt

    async def finalize_attempt(self, session: AsyncSession, attempt_id: str, *, status: str, outcome: str, receipt: Dict[str, Any], error_code: Optional[str] = None) -> RunAttemptRecord:
        attempt = await session.get(RunAttemptRecord, attempt_id)
        if not attempt:
            raise DomainError("resource_not_found", message="Run attempt was not found.")
        if attempt.status in TERMINAL_STATES:
            if attempt.outcome == outcome:
                return attempt
            raise DomainError("resource_conflict", message="Attempt was already finalized with a different outcome.")
        if status not in TERMINAL_STATES:
            raise DomainError("validation_failed", message="Attempt final status is invalid.")
        attempt.status = status
        attempt.outcome = outcome
        attempt.error_code = error_code
        attempt.receipt_json = json.dumps(receipt)
        attempt.completed_at = datetime.utcnow()
        await session.commit()
        await task_event_bus.publish(attempt.run_id, "attempt_completed", attempt_id=attempt.id, status=status, outcome=outcome)
        return attempt

    async def request_cancel(self, session: AsyncSession, run_id: str) -> TaskRun:
        run = await self._get(session, run_id)
        if run.status == "cancellation_requested":
            return run
        await self._transition(session, run, "cancellation_requested")
        run.cancellation_requested_at = datetime.utcnow()
        await session.commit()
        await task_event_bus.publish(run_id, "cancellation_requested", run_id=run_id)
        return run

    async def finalize(self, session: AsyncSession, run_id: str, status: str, reason: Optional[str] = None) -> TaskRun:
        run = await self._get(session, run_id)
        if status not in TERMINAL_STATES:
            raise DomainError("validation_failed", message="Run final status is invalid.")
        if run.status in TERMINAL_STATES:
            if run.status == status:
                return run
            raise DomainError("resource_conflict", message="Run was already finalized with a different status.")
        await self._transition(session, run, status)
        run.status_reason = reason
        run.completed_at = datetime.utcnow()
        await session.commit()
        await task_event_bus.publish(run_id, status, reason=reason)
        return run

    async def recover_interrupted(self, session: AsyncSession) -> list[str]:
        runs = (await session.execute(select(TaskRun).where(TaskRun.status.in_(["created", "running", "cancellation_requested"])))).scalars().all()
        recovered = []
        now = datetime.utcnow()
        for run in runs:
            attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == run.id, RunAttemptRecord.status.in_(["starting", "running"])))).scalars().all()
            for attempt in attempts:
                attempt.status = "interrupted"
                attempt.outcome = "interrupted"
                attempt.error_code = "service_restart"
                attempt.completed_at = now
                attempt.receipt_json = json.dumps({"outcome": "interrupted", "error_code": "service_restart"})
            run.status = "interrupted"
            run.status_reason = "service_restart"
            run.completed_at = now
            run.revision = (run.revision or 0) + 1
            recovered.append(run.id)
        await session.commit()
        for run_id in recovered:
            await task_event_bus.publish(run_id, "interrupted", reason="service_restart")
        return recovered

    async def _transition(self, session: AsyncSession, run: TaskRun, target: str) -> None:
        if target not in TRANSITIONS.get(run.status, set()):
            raise DomainError("resource_conflict", message=f"Invalid run transition: {run.status} -> {target}.")
        run.status = target
        run.revision = (run.revision or 0) + 1

    async def _get(self, session: AsyncSession, run_id: str) -> TaskRun:
        run = await session.get(TaskRun, run_id)
        if not run:
            raise DomainError("resource_not_found", message="Run was not found.")
        return run


run_lifecycle_service = RunLifecycleService()
