from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectRequirementEdgeRecord, ProjectRequirementRecord


class RequirementReadinessService:
    async def derive(self, session: AsyncSession, requirement_id: str) -> dict:
        requirement = await session.get(ProjectRequirementRecord, requirement_id)
        if not requirement:
            raise DomainError("resource_not_found", message="Requirement was not found.")
        edges = (await session.execute(select(ProjectRequirementEdgeRecord).where(ProjectRequirementEdgeRecord.project_id == requirement.project_id))).scalars().all()
        blockers = []
        for edge in edges:
            dependency_id = None
            if edge.edge_type == "requires" and edge.source_id == requirement_id:
                dependency_id = edge.target_id
            elif edge.edge_type == "blocks" and edge.target_id == requirement_id:
                dependency_id = edge.source_id
            if dependency_id:
                dependency = await session.get(ProjectRequirementRecord, dependency_id)
                if not dependency or dependency.status not in {"completed", "waived"}:
                    blockers.append({"requirement_id": dependency_id, "edge_type": edge.edge_type, "rationale": edge.rationale, "status": dependency.status if dependency else "missing"})
        eligible_status = requirement.status in {"approved", "blocked"}
        return {"requirement_id": requirement_id, "ready": eligible_status and not blockers, "derived_state": "ready" if eligible_status and not blockers else "blocked" if blockers else requirement.status, "blockers": sorted(blockers, key=lambda item: (item["requirement_id"], item["edge_type"])), "stored_status": requirement.status, "derivation_version": "1.0"}


requirement_readiness_service = RequirementReadinessService()
