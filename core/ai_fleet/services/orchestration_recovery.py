import json
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import OrchestrationCheckpointRecord,OrchestrationTaskRecord,TaskRun
class OrchestrationRecoveryService:
 async def save(self,s:AsyncSession,project_id,state,cursor,ready,active,locks,checkpoint_id=None,expected_revision=None):
  record=await s.get(OrchestrationCheckpointRecord,checkpoint_id) if checkpoint_id else None
  if record:
   if record.revision!=expected_revision:raise DomainError("stale_revision",details={"current_revision":record.revision})
   record.revision+=1
  else:record=OrchestrationCheckpointRecord(id=f"checkpoint-{uuid.uuid4().hex[:12]}",project_id=project_id,revision=1);s.add(record)
  record.state=state;record.cursor_json=json.dumps(cursor);record.ready_queue_json=json.dumps(ready);record.active_task_ids_json=json.dumps(active);record.lock_keys_json=json.dumps(sorted(set(locks)));await s.commit();return record
 async def recover(self,s:AsyncSession,checkpoint_id):
  record=await s.get(OrchestrationCheckpointRecord,checkpoint_id)
  if not record:raise DomainError("resource_not_found",message="Checkpoint was not found.")
  ready=[];duplicates=[]
  for task_id in json.loads(record.ready_queue_json):
   task=await s.get(OrchestrationTaskRecord,task_id)
   active=(await s.execute(select(TaskRun.id).where(TaskRun.project_id==record.project_id,TaskRun.status.in_(["created","running","cancellation_requested"]),TaskRun.id==task.current_run_id))).scalar_one_or_none() if task and task.current_run_id else None
   if active:duplicates.append(task_id)
   elif task and task.state in {"planned","ready"}:ready.append(task_id)
  return {"checkpoint":record.to_dict(),"safe_ready_queue":ready,"duplicate_dispatch_prevented":duplicates,"resume_state":record.state}
orchestration_recovery_service=OrchestrationRecoveryService()
