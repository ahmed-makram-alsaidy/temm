import json
import uuid
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import OrchestrationTaskRecord, ProjectRecord, ProjectRequirementRecord, TaskRun


class OrchestrationTaskService:
    async def create(self, session: AsyncSession, project_id: str, values: Dict[str, Any]) -> OrchestrationTaskRecord:
        project = await session.get(ProjectRecord, project_id)
        if not project or project.lifecycle_status != "active":
            raise DomainError("resource_not_found", message="Active project was not found.")
        acceptance = values.get("acceptance", [])
        if not acceptance or any(not item.get("criterion_id") or not item.get("description") for item in acceptance):
            raise DomainError("validation_failed", message="Task requires typed acceptance criteria.")
        for requirement_id in values.get("requirement_ids", []):
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            if not requirement or requirement.project_id != project_id:
                raise DomainError("validation_failed", message="Task requirement link is invalid.")
        for dependency_id in values.get("dependency_ids", []):
            dependency = await session.get(OrchestrationTaskRecord, dependency_id)
            if not dependency or dependency.project_id != project_id:
                raise DomainError("validation_failed", message="Task dependency link is invalid.")
        record = OrchestrationTaskRecord(
            id=f"task-{uuid.uuid4().hex[:12]}", project_id=project_id,
            task_type=values["task_type"], title=values["title"].strip(),
            description=values.get("description", ""),
            requirement_ids_json=json.dumps(values.get("requirement_ids", [])),
            dependency_ids_json=json.dumps(values.get("dependency_ids", [])),
            acceptance_json=json.dumps(acceptance),
            context_refs_json=json.dumps(values.get("context_refs", [])),
            executor_needs_json=json.dumps(values.get("executor_needs", {})), state="planned",
        )
        session.add(record)
        await session.commit()
        return record

    async def transition(self, session: AsyncSession, task_id: str, target: str, criteria: list[dict] | None = None, run_id: str | None = None) -> OrchestrationTaskRecord:
        task = await session.get(OrchestrationTaskRecord, task_id)
        if not task:
            raise DomainError("resource_not_found", message="Task was not found.")
        dependencies = [await session.get(OrchestrationTaskRecord, item) for item in json.loads(task.dependency_ids_json)]
        if target in {"ready", "running", "completed"} and any(not item or item.state != "completed" for item in dependencies):
            raise DomainError("resource_conflict", message="Task dependencies are not completed.")
        allowed = {"planned": {"ready", "blocked", "cancelled"}, "ready": {"running", "blocked", "cancelled"}, "running": {"completed", "failed", "blocked", "cancelled"}, "blocked": {"planned", "cancelled"}, "failed": {"planned", "cancelled"}}
        if target not in allowed.get(task.state, set()):
            raise DomainError("resource_conflict", message="Task transition is invalid.")
        if target == "completed":
            evidence = criteria or []
            required_ids = {item["criterion_id"] for item in json.loads(task.acceptance_json)}
            satisfied = {item.get("criterion_id") for item in evidence if item.get("status") in {"passed", "waived"} and (item.get("evidence") or item.get("waiver"))}
            run = await session.get(TaskRun, run_id) if run_id else None
            if required_ids - satisfied or not run or run.status != "completed" or run.project_id != task.project_id:
                raise DomainError("validation_failed", message="Task completion requires criteria evidence and a completed project run.")
            task.current_run_id = run_id
        task.state = target
        task.revision += 1
        await session.commit()
        return task


orchestration_task_service = OrchestrationTaskService()
