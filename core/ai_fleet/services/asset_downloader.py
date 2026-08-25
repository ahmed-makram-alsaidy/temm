import hashlib
from pathlib import Path
from typing import Any,AsyncIterator,Awaitable,Callable,Dict
from ..asset_sources import AssetDownloadPolicy
from ..errors import DomainError
from ..filesystem import PathPolicyError,path_policy
from ..storage.models import WorkspaceRecord
from ..url_safety import UrlSafetyPolicy,UrlSafetyService

class AssetDownloader:
 def __init__(self,streamer:Callable[[str],Awaitable[Dict[str,Any]]],safety:UrlSafetyService):self.streamer=streamer;self.safety=safety
 async def download(self,session,url:str,relative_path:str,policy:AssetDownloadPolicy):
  policy.validate();workspace=await session.get(WorkspaceRecord,policy.workspace_id)
  if not workspace:raise DomainError("resource_not_found",message="Approved workspace was not found.")
  url_policy=UrlSafetyPolicy(max_bytes=policy.max_bytes,allowed_content_types=("image/png","image/jpeg","image/webp","image/gif","image/svg+xml","audio/mpeg","audio/wav","video/mp4","application/pdf","application/json","font/woff","font/woff2","text/plain"))
  self.safety.validate(url,url_policy);destination=(Path(workspace.path)/relative_path)
  try:
   root=path_policy.existing_directory(workspace.path);parent=destination.parent.resolve(strict=True)
   if root!=parent and root not in parent.parents:raise PathPolicyError("Path is outside the approved workspace.")
  except (PathPolicyError,OSError) as exc:raise DomainError("validation_failed",message="Download destination is unsafe.") from exc
  response=await self.streamer(url);self.safety.validate_redirect_chain(response.get("redirect_chain",[url]),url_policy);self.safety.validate_response(response.get("content_type",""),response.get("content_length"),url_policy)
  quarantine=destination.with_name(destination.name+".quarantine");size=0;digest=hashlib.sha256()
  try:
   with quarantine.open("xb") as handle:
    async for chunk in response["chunks"]:
     size+=len(chunk)
     if size>policy.max_bytes:raise DomainError("validation_failed",message="Download exceeded size limit.")
     digest.update(chunk);handle.write(chunk)
   if destination.exists():raise DomainError("resource_conflict",message="Download destination already exists.")
   quarantine.replace(destination)
  except Exception:
   quarantine.unlink(missing_ok=True);raise
  return {"workspace_id":workspace.id,"relative_path":destination.relative_to(root).as_posix(),"size_bytes":size,"sha256":digest.hexdigest(),"content_type":response["content_type"].split(";",1)[0],"source_url":response.get("redirect_chain",[url])[-1],"approval_id":policy.approval_id,"quarantined_before_finalize":True,"provenance":"downloaded"}
