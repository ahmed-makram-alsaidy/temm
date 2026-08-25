import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import OrchestrationTaskRecord,ProjectNeedRecord
from .orchestration_tasks import OrchestrationTaskService
class NeedPlanningService:
 async def compile(self,s:AsyncSession,project_id:str):
  needs=(await s.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id==project_id,ProjectNeedRecord.state.in_(["open","in_progress"])).order_by(ProjectNeedRecord.created_at))).scalars().all();tasks=[];mapping={"information":"clarification","research":"research","asset":"asset_acquisition","dependency":"dependency_resolution","approval":"approval","capability":"capability_setup"}
  existing=(await s.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id==project_id))).scalars().all()
  for need in needs:
   found=next((t for t in existing if any(ref.get("need_id")==need.id for ref in json.loads(t.context_refs_json or "[]"))),None)
   if found:tasks.append(found);continue
   task=await OrchestrationTaskService().create(s,project_id,{"task_type":mapping[need.need_type],"title":f"Resolve: {need.title}","description":need.description,"requirement_ids":[need.requirement_id] if need.requirement_id else [],"acceptance":[{"criterion_id":f"need:{need.id}","description":"Need is resolved with evidence or explicitly waived"}],"context_refs":[{"source_type":"need","need_id":need.id}],"executor_needs":{"capabilities":[]}});tasks.append(task)
  return {"project_id":project_id,"task_ids":[t.id for t in tasks],"need_ids":[n.id for n in needs],"all_needs_planned":len(tasks)==len(needs)}
need_planning_service=NeedPlanningService()
