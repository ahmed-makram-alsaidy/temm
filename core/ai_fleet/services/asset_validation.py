import hashlib
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from ..filesystem import PathPolicyError,path_policy
from ..storage.models import AssetRecord,AssetUsageRecord,WorkspaceRecord
from sqlalchemy import select
class AssetValidationService:
 async def validate(self,s:AsyncSession,asset_id:str):
  asset=await s.get(AssetRecord,asset_id);findings=[]
  if not asset:return {"asset_id":asset_id,"findings":[{"code":"missing_record","severity":"critical","evidence":{}}],"valid":False}
  workspace=await s.get(WorkspaceRecord,asset.workspace_id)
  try:path=path_policy.contained_file(workspace.path,Path(workspace.path)/asset.relative_path) if workspace else None
  except PathPolicyError:path=None
  if not path:findings.append({"code":"missing_file","severity":"critical","evidence":{"workspace_id":asset.workspace_id,"relative_path":asset.relative_path}})
  else:
   raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
   if digest!=asset.sha256:findings.append({"code":"hash_changed","severity":"high","evidence":{"recorded":asset.sha256,"current":digest}})
   if len(raw)!=asset.size_bytes:findings.append({"code":"size_changed","severity":"medium","evidence":{"recorded":asset.size_bytes,"current":len(raw)}})
   if b"placeholder" in raw[:10000].lower() or b"todo image" in raw[:10000].lower():findings.append({"code":"placeholder_content","severity":"high","evidence":{"method":"bounded_marker_scan"}})
  if asset.state=="type_conflict" or asset.asset_type is None:findings.append({"code":"format_conflict","severity":"high","evidence":{"mime_type":asset.mime_type,"state":asset.state}})
  if not asset.license_id:findings.append({"code":"license_unknown","severity":"high","evidence":{}})
  usage=(await s.execute(select(AssetUsageRecord.id).where(AssetUsageRecord.asset_id==asset_id).limit(1))).scalar_one_or_none()
  if not usage:findings.append({"code":"unused_asset","severity":"info","evidence":{}})
  return {"asset_id":asset_id,"findings":findings,"valid":not any(x["severity"] in {"critical","high"} for x in findings)}
asset_validation_service=AssetValidationService()
