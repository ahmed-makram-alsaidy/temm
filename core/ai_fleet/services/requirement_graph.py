import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectRequirementEdgeRecord, ProjectRequirementRecord


EDGE_TYPES = {"requires", "blocks", "relates", "conflicts"}
ORDERING_TYPES = {"requires", "blocks"}


class RequirementGraphService:
    async def add(self, session: AsyncSession, source_id: str, target_id: str, edge_type: str, rationale: str) -> ProjectRequirementEdgeRecord:
        source = await session.get(ProjectRequirementRecord, source_id); target = await session.get(ProjectRequirementRecord, target_id)
        if not source or not target or source.project_id != target.project_id or source_id == target_id or edge_type not in EDGE_TYPES or len(rationale.strip()) < 3:
            raise DomainError("validation_failed", message="Requirement dependency edge is invalid.")
        existing = (await session.execute(select(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.source_id == source_id, ProjectRequirementEdgeRecord.target_id == target_id, ProjectRequirementEdgeRecord.edge_type == edge_type))).scalar_one_or_none()
        if existing: return existing
        if edge_type in ORDERING_TYPES and await self._reachable(session, target_id, source_id): raise DomainError("resource_conflict", message="Requirement dependency would create a cycle.")
        record = ProjectRequirementEdgeRecord(id=f"requirement-edge-{uuid.uuid4().hex[:12]}", project_id=source.project_id, source_id=source_id, target_id=target_id, edge_type=edge_type, rationale=rationale.strip())
        session.add(record); await session.commit(); return record

    async def list(self, session: AsyncSession, project_id: str) -> List[ProjectRequirementEdgeRecord]:
        return (await session.execute(select(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id == project_id).order_by(ProjectRequirementEdgeRecord.created_at))).scalars().all()

    async def impact(self, session: AsyncSession, requirement_id: str) -> List[dict]:
        requirement = await session.get(ProjectRequirementRecord, requirement_id)
        if not requirement: raise DomainError("resource_not_found", message="Requirement was not found.")
        edges = (await session.execute(select(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id == requirement.project_id))).scalars().all()
        adjacency = {}
        direct = []
        for edge in edges:
            if edge.edge_type == "requires": adjacency.setdefault(edge.target_id, []).append((edge.source_id, edge))
            elif edge.edge_type == "blocks": adjacency.setdefault(edge.source_id, []).append((edge.target_id, edge))
            elif requirement_id in {edge.source_id, edge.target_id}:
                other = edge.target_id if edge.source_id == requirement_id else edge.source_id
                direct.append({"requirement_id": other, "impact_type": edge.edge_type, "path": [requirement_id, other], "reasons": [edge.rationale]})
        results = {}; queue = [(requirement_id, [requirement_id], [])]
        while queue:
            node, path, reasons = queue.pop(0)
            for target, edge in sorted(adjacency.get(node, []), key=lambda item: (item[0], item[1].edge_type)):
                if target in path: continue
                next_path, next_reasons = [*path, target], [*reasons, edge.rationale]
                if target not in results or len(next_path) < len(results[target]["path"]): results[target] = {"requirement_id": target, "impact_type": "downstream", "path": next_path, "reasons": next_reasons}
                queue.append((target, next_path, next_reasons))
        for item in direct:
            results.setdefault(item["requirement_id"], item)
        return [results[key] for key in sorted(results)]

    async def _reachable(self, session: AsyncSession, start: str, target: str) -> bool:
        edges = (await session.execute(select(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.edge_type.in_(ORDERING_TYPES)))).scalars().all()
        graph = {}
        for edge in edges: graph.setdefault(edge.source_id, []).append(edge.target_id)
        stack = [start]; seen = set()
        while stack:
            node = stack.pop()
            if node == target: return True
            if node in seen: continue
            seen.add(node); stack.extend(graph.get(node, []))
        return False


requirement_graph_service = RequirementGraphService()
