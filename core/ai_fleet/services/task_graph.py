import json
from collections import deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import OrchestrationTaskRecord


class TaskGraphService:
    async def derive(self, session: AsyncSession, project_id: str) -> dict:
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id))).scalars().all()
        by_id = {task.id: task for task in tasks}
        dependencies = {task.id: list(dict.fromkeys(json.loads(task.dependency_ids_json))) for task in tasks}
        for task_id, items in dependencies.items():
            if task_id in items or any(item not in by_id for item in items):
                raise DomainError("validation_failed", message="Task graph contains an invalid dependency.")
        outgoing = {task_id: [] for task_id in by_id}
        indegree = {task_id: len(items) for task_id, items in dependencies.items()}
        for task_id, items in dependencies.items():
            for dependency in items:
                outgoing[dependency].append(task_id)
        queue = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for target in sorted(outgoing[node]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(order) != len(tasks):
            raise DomainError("resource_conflict", message="Task dependency graph contains a cycle.")
        longest = {}
        predecessor = {}
        for node in order:
            candidates = [(longest[dependency] + 1, dependency) for dependency in dependencies[node]]
            if candidates:
                length, parent = max(candidates, key=lambda item: (item[0], item[1]))
                longest[node], predecessor[node] = length, parent
            else:
                longest[node] = 1
        end = max(order, key=lambda item: (longest[item], item)) if order else None
        critical = []
        while end:
            critical.append(end)
            end = predecessor.get(end)
        critical.reverse()
        ready = [task_id for task_id in order if by_id[task_id].state == "planned" and all(by_id[item].state == "completed" for item in dependencies[task_id])]
        return {"project_id": project_id, "topological_order": order, "critical_path": critical, "critical_path_units": len(critical), "ready_queue": ready, "dependencies": dependencies, "graph_version": "1.0"}


task_graph_service = TaskGraphService()
