from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import AssetRecord,OrchestrationTaskRecord,ProjectNeedRecord,ProjectRequirementRecord
from .asset_validation import AssetValidationService
from .definition_of_done import DefinitionOfDoneService
from .quality_workspace import QualityWorkspaceService
class CompletionAssessmentService:
 async def assess(self,s:AsyncSession,project_id:str):
  requirements=(await s.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id==project_id))).scalars().all();tasks=(await s.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id==project_id))).scalars().all();assets=(await s.execute(select(AssetRecord).where(AssetRecord.project_id==project_id))).scalars().all();needs=(await s.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id==project_id,ProjectNeedRecord.impact=="blocking",ProjectNeedRecord.state.in_(["open","in_progress"])))).scalars().all()
  req_block=[{"requirement_id":r.id,"status":r.status} for r in requirements if r.status not in {"completed","waived"}]
  task_results=[await DefinitionOfDoneService().assess(s,t.id) for t in tasks];asset_results=[await AssetValidationService().validate(s,a.id) for a in assets];quality=await QualityWorkspaceService().summary(s,project_id)
  blockers={"requirements":req_block,"tasks":[x for x in task_results if not x["done"] and not x["settled"]],"assets":[x for x in asset_results if not x["valid"]],"needs":[n.to_dict() for n in needs],"quality":quality["blocking_findings"]}
  readiness_blockers = {**blockers}
  if not requirements:
   readiness_blockers["requirements"] = [{"status": "missing", "reason": "project_has_no_requirements"}]
  ready=all(not value for value in readiness_blockers.values())
  return {"project_id":project_id,"ready":ready,"done":ready,"blockers":readiness_blockers,"evidence":{"requirements":len(requirements),"tasks":task_results,"assets":asset_results,"quality_generated_at":quality["generated_at"]},"assessment_version":"1.0","statement":"Delivery readiness established by evidence." if ready else "Delivery readiness blocked by unresolved evidence."}
completion_assessment_service=CompletionAssessmentService()
