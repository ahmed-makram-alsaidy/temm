import json
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import OrchestrationCheckpointRecord
from .orchestration_recovery import OrchestrationRecoveryService
TRANSITIONS={"new":{"analyzed"},"analyzed":{"planned"},"planned":{"approved"},"approved":{"running"},"running":{"paused","cancelled","completed"},"paused":{"running","cancelled"}}
class OrchestrationCommandService:
 async def create(self,s:AsyncSession,project_id):return await OrchestrationRecoveryService().save(s,project_id,"new",{},[],[],[])
 async def command(self,s:AsyncSession,orchestration_id,action,payload=None):
  record=await s.get(OrchestrationCheckpointRecord,orchestration_id)
  if not record:raise DomainError("resource_not_found",message="Orchestration was not found.")
  target={"analyze":"analyzed","plan":"planned","approve":"approved","start":"running","pause":"paused","resume":"running","cancel":"cancelled"}.get(action)
  if not target:raise DomainError("validation_failed",message="Orchestration command is invalid.")
  if record.state==target:return record
  if target not in TRANSITIONS.get(record.state,set()):raise DomainError("resource_conflict",message=f"Invalid orchestration transition: {record.state} -> {target}.")
  cursor=json.loads(record.cursor_json or "{}");cursor[action]=payload or {};return await OrchestrationRecoveryService().save(s,record.project_id,target,cursor,json.loads(record.ready_queue_json),json.loads(record.active_task_ids_json),json.loads(record.lock_keys_json),record.id,record.revision)
orchestration_command_service=OrchestrationCommandService()
