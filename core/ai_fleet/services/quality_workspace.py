from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import AcceptanceCriterionRecord, AssetRecord, OrchestrationTaskRecord, ProjectRequirementRecord, QualityWaiverRecord
from .asset_validation import AssetValidationService
from .definition_of_done import DefinitionOfDoneService


class QualityWorkspaceService:
    async def summary(self, session: AsyncSession, project_id: str) -> dict:
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id))).scalars().all()
        requirements = (await session.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == project_id))).scalars().all()
        assets = (await session.execute(select(AssetRecord).where(AssetRecord.project_id == project_id))).scalars().all()
        waivers = (await session.execute(select(QualityWaiverRecord).where(QualityWaiverRecord.project_id == project_id).order_by(QualityWaiverRecord.created_at.desc()))).scalars().all()
        task_results = []
        findings = []
        for task in tasks:
            assessment = await DefinitionOfDoneService().assess(session, task.id)
            task_results.append(assessment)
            if assessment["settled"]:
                # A retired or superseded task is not outstanding work, so its unmet
                # blockers are not quality findings about the workspace - a cancelled task
                # can never acquire the completed run its assessment asks for. The task is
                # still reported in `tasks` with its blockers and its settlement ground
                # intact, so nothing is hidden; it just stops being counted against
                # readiness twice over. See DefinitionOfDoneService._settlement.
                continue
            for blocker in assessment["blockers"]:
                findings.append({"id": f"task:{task.id}:{blocker}", "source": "task", "severity": "high", "code": blocker, "evidence": {"task_id": task.id, "task_state": task.state}})
        for requirement in requirements:
            if requirement.status in {"approved", "blocked"} and not requirement.to_dict()["evidence"]:
                findings.append({"id": f"requirement:{requirement.id}:evidence", "source": "requirement", "severity": "high", "code": "requirement_evidence_missing", "evidence": {"requirement_id": requirement.id}})
        for asset in assets:
            validation = await AssetValidationService().validate(session, asset.id)
            for finding in validation["findings"]:
                findings.append({"id": f"asset:{asset.id}:{finding['code']}", "source": "asset", **finding})
        now = datetime.utcnow()
        waiver_payload = []
        effective_findings = []
        for finding in findings:
            waiver = next((item for item in waivers if item.finding_id == finding["id"] and item.status == "active" and item.expires_at > now), None)
            if waiver:
                finding = {**finding, "status": "waived", "waiver_id": waiver.id}
            effective_findings.append(finding)
        for waiver in waivers:
            waiver_payload.append({**waiver.to_dict(), "effective": waiver.status == "active" and waiver.expires_at > now})
        blocking = [item for item in effective_findings if item.get("severity") in {"critical", "high"} and item.get("status") != "waived"]
        advisory = [item for item in effective_findings if item not in blocking]
        return {"project_id": project_id, "ready": not blocking and all(item["done"] or item["settled"] for item in task_results), "blocking_findings": blocking, "advisory_findings": advisory, "tasks": task_results, "waivers": waiver_payload, "readiness_explanation": "Ready requires every task either proven done or settled as retired or superseded, and no unwaived high or critical findings.", "generated_at": now.isoformat(), "summary_version": "1.0"}


quality_workspace_service = QualityWorkspaceService()
