from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from .approvals import ApprovalService
class OrchestrationApprovalService:
 def __init__(self):self.approvals=ApprovalService()
 async def escalate(self,s:AsyncSession,orchestration_id:str,reason_type:str,summary:str,evidence:dict):
  if reason_type not in {"quality","spend","destructive","missing_decision"}:raise DomainError("validation_failed",message="Escalation reason is invalid.")
  record=await self.approvals.request(s,action_type=reason_type,scope_type="orchestration",scope_id=orchestration_id,summary=summary,details=evidence,ttl_seconds=86400)
  return {"orchestration_id":orchestration_id,"state":"paused_approval","approval":record.to_dict(),"durable":True,"reason_type":reason_type}
 async def resume(self,s:AsyncSession,approval_id:str,orchestration_id:str,reason_type:str):
  record=await self.approvals.consume(s,approval_id,reason_type,"orchestration",orchestration_id);return {"orchestration_id":orchestration_id,"state":"resumable","approval":record.to_dict()}
orchestration_approval_service=OrchestrationApprovalService()
