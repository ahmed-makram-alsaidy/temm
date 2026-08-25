import json
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import AcceptanceCriterionRecord,OrchestrationTaskRecord
class AcceptanceService:
 async def create(self,s:AsyncSession,task_id,values):
  if not await s.get(OrchestrationTaskRecord,task_id) or values["severity"] not in {"info","low","medium","high","critical"} or not values.get("evaluator"):raise DomainError("validation_failed",message="Acceptance criterion is invalid.")
  record=AcceptanceCriterionRecord(id=f"criterion-{uuid.uuid4().hex[:12]}",task_id=task_id,criterion_type=values["criterion_type"],description=values["description"],evaluator=values["evaluator"],severity=values["severity"]);s.add(record);await s.commit();return record
 async def decide(self,s:AsyncSession,criterion_id,status,evidence=None,waiver=None):
  record=await s.get(AcceptanceCriterionRecord,criterion_id)
  if not record or record.status!="pending" or status not in {"passed","failed","waived"}:raise DomainError("resource_conflict",message="Criterion transition is invalid.")
  if status=="passed" and not evidence:raise DomainError("validation_failed",message="Passing criterion requires evidence.")
  if status=="waived" and (not waiver or not waiver.get("actor") or len(waiver.get("rationale","").strip())<10):raise DomainError("validation_failed",message="Waiver requires actor and rationale.")
  record.status=status;record.evidence_json=json.dumps(evidence or []);record.waiver_json=json.dumps(waiver) if waiver else None;await s.commit();return record
acceptance_service=AcceptanceService()
