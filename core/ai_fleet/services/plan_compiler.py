import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import BlueprintProposalRecord, OrchestrationTaskRecord, ProjectNeedRecord, ProjectRequirementRecord
from .orchestration_tasks import OrchestrationTaskService
from .task_graph import TaskGraphService


class PlanCompilerService:
    async def compile(self, session: AsyncSession, project_id: str, proposal_id: str):
        proposal = await session.get(BlueprintProposalRecord, proposal_id)
        if not proposal or proposal.project_id != project_id or proposal.status != "approved":
            raise DomainError("resource_conflict", message="Approved blueprint proposal is required.")
        requirements = (await session.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == project_id, ProjectRequirementRecord.status.in_(["approved", "blocked"])))).scalars().all()
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id))).scalars().all()
        created = []
        for requirement in requirements:
            existing = next((task for task in tasks if requirement.id in json.loads(task.requirement_ids_json or "[]")), None)
            if existing:
                created.append(existing)
                continue
            needs = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.requirement_id == requirement.id, ProjectNeedRecord.state.in_(["open", "in_progress"])))).scalars().all()
            need_ids = {need.id for need in needs}
            dependencies = [task.id for task in tasks if any(ref.get("need_id") in need_ids for ref in json.loads(task.context_refs_json or "[]"))]
            acceptance = [
                {
                    "criterion_id": f"requirement:{requirement.id}:{index}",
                    "description": item.get("statement") or item.get("description") or "Requirement acceptance evidence is satisfied",
                    "evaluator": item.get("evaluator", {}),
                }
                for index, item in enumerate(json.loads(requirement.acceptance_json or "[]"))
            ] or [{"criterion_id": f"requirement:{requirement.id}", "description": "Requirement acceptance and evidence are satisfied"}]
            task = await OrchestrationTaskService().create(session, project_id, {
                "task_type": "requirement_implementation", "title": requirement.title, "description": requirement.description,
                "requirement_ids": [requirement.id], "dependency_ids": dependencies, "acceptance": acceptance,
                "context_refs": [{"source_type": "requirement", "source_id": requirement.id, "revision": requirement.revision}, {"source_type": "blueprint", "source_id": proposal_id, "revision": proposal.revision}],
                "executor_needs": {"capabilities": ["coding"]},
            })
            tasks.append(task)
            created.append(task)
        graph = await TaskGraphService().derive(session, project_id)
        return {"project_id": project_id, "proposal_id": proposal_id, "template_id": proposal.template_id, "template_version": proposal.template_version, "requirement_ids": [requirement.id for requirement in requirements], "task_ids": [task.id for task in created], "graph": graph, "traceable": True, "dispatch_started": False, "compiler_version": "1.0"}


plan_compiler_service = PlanCompilerService()
