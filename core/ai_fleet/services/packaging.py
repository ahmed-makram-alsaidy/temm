import hashlib
import io
import json
import re
import zipfile
from pathlib import Path,PurePosixPath
from ..errors import DomainError
from ..filesystem import PathPolicyError,path_policy
class PackagingService:
 def package(self,workspace:str,relative_paths:list[str]):
  root=path_policy.existing_directory(workspace);files=[];secret=re.compile(rb"(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}",re.I)
  for value in sorted(set(relative_paths)):
   archive=PurePosixPath(value.replace("\\","/"))
   if archive.is_absolute() or ".." in archive.parts:raise DomainError("validation_failed",message="Package path is unsafe.")
   try:path=path_policy.contained_file(root,root/Path(value))
   except PathPolicyError as exc:raise DomainError("validation_failed",message=str(exc)) from exc
   data=path.read_bytes()
   if secret.search(data):raise DomainError("permission_denied",message="Package contains a potential secret.",details={"path":archive.as_posix()})
   files.append((archive.as_posix(),data,hashlib.sha256(data).hexdigest()))
  manifest={"schema_version":"1.0","files":[{"path":name,"size":len(data),"sha256":digest} for name,data,digest in files]};manifest_bytes=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode();manifest["manifest_sha256"]=hashlib.sha256(manifest_bytes).hexdigest()
  output=io.BytesIO()
  with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
   for name,data,digest in files:
    info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,data)
   info=zipfile.ZipInfo("MANIFEST.json",(1980,1,1,0,0,0));info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,json.dumps(manifest,sort_keys=True,indent=2).encode())
  payload=output.getvalue();return {"archive":payload,"archive_sha256":hashlib.sha256(payload).hexdigest(),"manifest":manifest,"reproducible":True}
packaging_service=PackagingService()
