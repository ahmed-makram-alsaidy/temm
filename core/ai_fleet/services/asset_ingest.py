import hashlib
import mimetypes
import uuid
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from ..assets import classify_asset
from ..errors import DomainError
from ..filesystem import PathPolicyError,path_policy
from ..storage.models import AssetRecord,ProjectRecord,WorkspaceRecord

class AssetIngestService:
 async def ingest(self,session:AsyncSession,workspace_id:str,relative_path:str,scope_type:str="global",project_id:Optional[str]=None,source_type:str="user",source_id:Optional[str]=None,provenance:str="user_declared",license_id:Optional[str]=None):
  workspace=await session.get(WorkspaceRecord,workspace_id)
  if not workspace or scope_type not in {"project","global"} or scope_type=="project" and (not project_id or not await session.get(ProjectRecord,project_id)): raise DomainError("validation_failed",message="Asset scope or workspace is invalid.")
  try: path=path_policy.contained_file(workspace.path,Path(workspace.path)/relative_path)
  except PathPolicyError as exc: raise DomainError("validation_failed",message=str(exc)) from exc
  size=path.stat().st_size
  if size<=0 or size>50*1024*1024: raise DomainError("validation_failed",message="Asset size is outside the 1 byte to 50 MiB limit.")
  raw=path.read_bytes(); mime=self._mime(raw,path.name); classification=classify_asset(path.name,mime); relative=path.relative_to(Path(workspace.path).resolve()).as_posix()
  record=AssetRecord(id=f"asset-{uuid.uuid4().hex[:12]}",scope_type=scope_type,project_id=project_id,workspace_id=workspace_id,relative_path=relative,asset_type=classification["canonical_type"],mime_type=mime,sha256=hashlib.sha256(raw).hexdigest(),source_type=source_type,source_id=source_id,provenance=provenance,license_id=license_id,size_bytes=size,state="type_conflict" if classification["conflict"] else "ready",metadata_json=__import__("json").dumps({"classification":classification}))
  session.add(record); await session.commit(); return record
 def _mime(self,raw:bytes,name:str):
  signatures=[(b"\x89PNG\r\n\x1a\n","image/png"),(b"\xff\xd8\xff","image/jpeg"),(b"GIF87a","image/gif"),(b"GIF89a","image/gif"),(b"%PDF-","application/pdf"),(b"RIFF","audio/wav")]
  for signature,mime in signatures:
   if raw.startswith(signature): return mime
  head=raw[:1024].lstrip()
  if head.startswith(b"<svg") or b"<svg" in head[:300]: return "image/svg+xml"
  if b"\x00" not in raw[:8192]: return mimetypes.guess_type(name)[0] or "text/plain"
  return "application/octet-stream"
asset_ingest_service=AssetIngestService()
