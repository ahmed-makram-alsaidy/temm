import json
from collections import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import ProjectNeedRecord
class NeedsValueService:
 async def aggregate(self,s:AsyncSession,project_id:str):
  rows=(await s.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id==project_id))).scalars().all();unique={row.dedupe_key:row for row in rows};resolved=[]
  for row in unique.values():
   if row.state=="resolved" and row.resolution_json:
    evidence=json.loads(row.resolution_json)
    if evidence:resolved.append({"need_id":row.id,"need_type":row.need_type,"evidence":evidence})
  return {"project_id":project_id,"discovered":len(unique),"resolved_with_evidence":len(resolved),"open":sum(row.state in {"open","in_progress"} for row in unique.values()),"by_type":dict(Counter(row.need_type for row in unique.values())),"resolution_evidence":resolved,"provenance":"measured","dedupe_scope":"project+dedupe_key"}
needs_value_service=NeedsValueService()
