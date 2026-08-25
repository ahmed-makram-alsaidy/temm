import json
from collections import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import OrchestrationTaskRecord
from .definition_of_done import DefinitionOfDoneService
class AutomationValueService:
 async def aggregate(self,s:AsyncSession,project_id:str):
  tasks=(await s.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id==project_id))).scalars().all();verified=[];keys=[]
  for task in tasks:
   assessment=await DefinitionOfDoneService().assess(s,task.id)
   if not assessment["done"]:continue
   verified.append({"task_id":task.id,"run_id":assessment["run_id"]});key=json.loads(task.executor_needs_json or "{}").get("repeated_work_key")
   if key:keys.append(key)
  counts=Counter(keys);avoided=sum(max(0,count-1) for count in counts.values())
  return {"project_id":project_id,"verified_completed_tasks":len(verified),"repeated_work_avoided":avoided,"evidence":verified,"repeated_work_groups":dict(counts),"provenance":"measured","failed_or_unverified_excluded":len(tasks)-len(verified)}
automation_value_service=AutomationValueService()
