import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import ProjectRecord,QualityWaiverRecord
class QualityWaiverService:
 async def create(self,s:AsyncSession,project_id,finding_id,scope_type,scope_id,reason,risk,owner,expires_at):
  if not await s.get(ProjectRecord,project_id) or scope_type not in {"task","project","deliverable","gate"} or len(reason.strip())<10 or len(risk.strip())<5 or expires_at<=datetime.utcnow():raise DomainError("validation_failed",message="Quality waiver is invalid.")
  record=QualityWaiverRecord(id=f"waiver-{uuid.uuid4().hex[:12]}",project_id=project_id,finding_id=finding_id,scope_type=scope_type,scope_id=scope_id,reason=reason.strip(),risk=risk.strip(),owner=owner,expires_at=expires_at,status="active");s.add(record);await s.commit();return record
 def current(self,record,at=None):
  at=at or datetime.utcnow();return {**record.to_dict(),"effective":record.status=="active" and record.expires_at>at,"finding_status":"waived","passed":False}
quality_waiver_service=QualityWaiverService()
