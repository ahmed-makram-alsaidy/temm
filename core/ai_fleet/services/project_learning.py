import json
import uuid
from collections import defaultdict
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectLearningConsentRecord, ProjectOutcomeRecord, ProjectRecord, TaskRun


class ProjectLearningService:
    async def consent(self, session: AsyncSession, project_id: str, enabled: bool, actor: str):
        if not await session.get(ProjectRecord, project_id): raise DomainError("resource_not_found", message="Project was not found.")
        record = await session.get(ProjectLearningConsentRecord, project_id) or ProjectLearningConsentRecord(project_id=project_id)
        record.enabled = enabled; record.granted_by = actor if enabled else None; session.add(record); await session.commit(); return {"project_id": project_id, "enabled": enabled, "granted_by": record.granted_by}
    async def record(self, session: AsyncSession, project_id: str, run_id: str, category: str, route_id: str, outcome: str, preferred: bool, evidence: Dict[str, Any]):
        consent = await session.get(ProjectLearningConsentRecord, project_id); run = await session.get(TaskRun, run_id)
        if not consent or not consent.enabled: raise DomainError("permission_denied", message="Project learning requires explicit consent.")
        if not run or run.project_id != project_id or outcome not in {"success", "failure", "accepted", "rejected"}: raise DomainError("validation_failed", message="Project outcome evidence is invalid.")
        record = ProjectOutcomeRecord(id=f"outcome-{uuid.uuid4().hex[:12]}", project_id=project_id, run_id=run_id, task_category=category, route_id=route_id, outcome=outcome, preferred=preferred, evidence_json=json.dumps(evidence))
        session.add(record); await session.commit(); return record
    async def recommend(self, session: AsyncSession, project_id: str, category: str):
        consent = await session.get(ProjectLearningConsentRecord, project_id)
        if not consent or not consent.enabled: return {"available": False, "reason": "consent_required", "sample_size": 0}
        rows = (await session.execute(select(ProjectOutcomeRecord).where(ProjectOutcomeRecord.project_id == project_id, ProjectOutcomeRecord.task_category == category))).scalars().all()
        grouped = defaultdict(list)
        for row in rows: grouped[row.route_id].append(row)
        candidates = []
        for route, items in grouped.items():
            wins = sum(1 for item in items if item.preferred and item.outcome in {"success", "accepted"})
            candidates.append({"route_id": route, "sample_size": len(items), "preferred_successes": wins, "preferred_success_rate": wins / len(items), "evidence_run_ids": [item.run_id for item in items]})
        candidates.sort(key=lambda item: (-item["preferred_success_rate"], -item["sample_size"], item["route_id"]))
        return {"available": bool(candidates), "reason": "evidence_available" if candidates else "insufficient_evidence", "sample_size": len(rows), "recommendation": candidates[0] if candidates else None, "candidates": candidates, "consent": {"enabled": True, "granted_by": consent.granted_by}}


project_learning_service = ProjectLearningService()
