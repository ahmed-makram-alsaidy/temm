import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import ProjectRequirementRecord
class BusinessRequirementGateService:
 async def assess(self,s:AsyncSession,project_id:str):
  rows=(await s.execute(select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id==project_id,ProjectRequirementRecord.status.in_(["approved","blocked","completed","waived"])))).scalars().all();results=[]
  for req in rows:
   evidence=json.loads(req.evidence_json);waived=req.status=="waived" and bool(req.waiver_rationale);passed=req.status=="completed" and bool(evidence) or waived
   results.append({"requirement_id":req.id,"status":"passed" if passed else "blocked","stored_status":req.status,"evidence":evidence,"waiver":{"actor":req.waived_by,"rationale":req.waiver_rationale} if waived else None,"reason":None if passed else "verified_behavior_evidence_missing"})
  return {"project_id":project_id,"results":results,"passed":all(x["status"]=="passed" for x in results),"gate_version":"1.0"}
business_requirement_gate_service=BusinessRequirementGateService()
