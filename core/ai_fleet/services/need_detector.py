import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import ProjectBrainFactRecord, ProjectNeedRecord, ProjectRequirementRecord


class NeedDetectorService:
    async def detect(self, session: AsyncSession, project_id: str, asset_needs: list[ProjectNeedRecord], quality_findings: list[dict]) -> list[ProjectNeedRecord]:
        proposals = []
        facts = (await session.execute(select(ProjectBrainFactRecord).where(ProjectBrainFactRecord.project_id == project_id, ProjectBrainFactRecord.truth_state == "unknown"))).scalars().all()
        for fact in facts:
            proposals.append({"dedupe_key": f"information:{fact.id}", "need_type": "information", "title": f"Clarify {fact.section}.{fact.fact_key}", "description": "Confirmed owner information is required.", "source_type": "brain_fact", "source_id": fact.id, "impact": "blocking", "blocked_nodes": [fact.id]})
        requirements = (await session.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == project_id, ProjectRequirementRecord.status == "blocked"))).scalars().all()
        for requirement in requirements:
            proposals.append({"dedupe_key": f"dependency:{requirement.id}", "need_type": "dependency", "title": f"Resolve blocked requirement: {requirement.title}", "description": "Requirement readiness is blocked.", "source_type": "requirement", "source_id": requirement.id, "impact": "blocking", "blocked_nodes": [requirement.id], "requirement_id": requirement.id})
        for need in asset_needs:
            proposals.append({"existing": need})
        for finding in quality_findings:
            if finding.get("severity") in {"critical", "high"}:
                proposals.append({"dedupe_key": f"quality:{finding['id']}", "need_type": "approval" if finding.get("waivable") else "capability", "title": f"Resolve quality blocker: {finding.get('code')}", "description": json.dumps(finding.get("evidence", {}), sort_keys=True), "source_type": "quality_finding", "source_id": finding["id"], "impact": "blocking", "blocked_nodes": finding.get("blocked_nodes", [])})
        results = []
        for proposal in proposals:
            if proposal.get("existing"):
                results.append(proposal["existing"])
                continue
            existing = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == project_id, ProjectNeedRecord.dedupe_key == proposal["dedupe_key"]))).scalar_one_or_none()
            if existing:
                results.append(existing)
                continue
            record = ProjectNeedRecord(id=f"need-{uuid.uuid4().hex[:12]}", project_id=project_id, requirement_id=proposal.get("requirement_id"), need_type=proposal["need_type"], title=proposal["title"], description=proposal["description"], source_type=proposal["source_type"], source_id=proposal["source_id"], impact=proposal["impact"], blocked_nodes_json=json.dumps(proposal["blocked_nodes"]), state="open", dedupe_key=proposal["dedupe_key"])
            session.add(record)
            results.append(record)
        await session.commit()
        return results


need_detector_service = NeedDetectorService()
