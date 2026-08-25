from typing import Any, Awaitable, Callable, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import TaskRun
from .runs import run_lifecycle_service


RETRYABLE_ERRORS = {"rate_limited", "provider_unavailable", "network_error", "launch_failed", "timed_out", "temporary_failure"}
TERMINAL_ERRORS = {"auth_failed", "permission_denied", "invalid_output", "cancelled", "validation_failed"}
Executor = Callable[[Dict[str, Any], str], Awaitable[Dict[str, Any]]]


class FallbackService:
    async def execute(self, session: AsyncSession, run_id: str, routes: List[Dict[str, Any]], executor: Executor) -> Dict[str, Any]:
        if not routes or len(routes) > 20:
            raise DomainError("validation_failed", message="Fallback chain must contain between one and twenty routes.")
        if len({route.get("route_id") for route in routes}) != len(routes) or any(not route.get("executable") for route in routes):
            raise DomainError("validation_failed", message="Fallback routes must be distinct and preflight executable.")
        attempts = []
        for route in routes:
            run = await session.get(TaskRun, run_id)
            if not run:
                raise DomainError("resource_not_found", message="Run was not found.")
            if run.status == "cancellation_requested":
                await run_lifecycle_service.finalize(session, run_id, "cancelled", "cancellation_requested")
                return {"run_id": run_id, "status": "cancelled", "attempts": attempts, "selected_route_id": None}
            if run.status != "running":
                raise DomainError("resource_conflict", message="Fallback execution requires a running run.")
            attempt = await run_lifecycle_service.start_attempt(session, run_id, route.get("executor_type", "provider"), route.get("agent_id"), route.get("model_id"), route.get("provider_instance_id"))
            result = await executor(route, attempt.id)
            outcome = result.get("outcome", "failed")
            error_code = result.get("error_code")
            success = bool(result.get("success"))
            status = "completed" if success else "cancelled" if error_code == "cancelled" else "timed_out" if error_code == "timed_out" else "failed"
            receipt = {key: value for key, value in result.items() if key not in {"stdout", "stderr", "content"}}
            receipt.update({"route_id": route["route_id"], "fallback_index": len(attempts)})
            await run_lifecycle_service.finalize_attempt(session, attempt.id, status=status, outcome=outcome, receipt=receipt, error_code=error_code)
            attempts.append({"attempt_id": attempt.id, "route_id": route["route_id"], "status": status, "error_code": error_code})
            if success:
                await run_lifecycle_service.finalize(session, run_id, "completed")
                return {"run_id": run_id, "status": "completed", "attempts": attempts, "selected_route_id": route["route_id"]}
            run = await session.get(TaskRun, run_id)
            if error_code == "cancelled" or run.status == "cancellation_requested":
                await run_lifecycle_service.finalize(session, run_id, "cancelled", error_code or "cancellation_requested")
                return {"run_id": run_id, "status": "cancelled", "attempts": attempts, "selected_route_id": None}
            if error_code in TERMINAL_ERRORS or error_code not in RETRYABLE_ERRORS:
                await run_lifecycle_service.finalize(session, run_id, status, error_code or "non_retryable_failure")
                return {"run_id": run_id, "status": status, "attempts": attempts, "selected_route_id": None}
        await run_lifecycle_service.finalize(session, run_id, "failed", "fallback_exhausted")
        return {"run_id": run_id, "status": "failed", "attempts": attempts, "selected_route_id": None}


fallback_service = FallbackService()
