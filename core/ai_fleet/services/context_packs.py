import json
import uuid
from typing import Any, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from ..context import ContextSource
from ..errors import DomainError
from ..storage.models import ContextPackRecord

class ContextPackService:
    async def create(self,session:AsyncSession,sources:List[ContextSource],token_count:int,token_provenance:str,token_method:str|None=None,redactions:List[Dict[str,Any]]|None=None,project_id:str|None=None,run_id:str|None=None):
        if token_count<0 or token_provenance not in {"measured","estimated"} or token_provenance=="estimated" and not token_method: raise DomainError("validation_failed",message="Context pack token evidence is invalid.")
        manifest=[source.validate().to_dict() for source in sources]
        record=ContextPackRecord(id=f"context-{uuid.uuid4().hex[:12]}",project_id=project_id,run_id=run_id,manifest_json=json.dumps(manifest,sort_keys=True),token_count=token_count,token_provenance=token_provenance,token_method=token_method,redactions_json=json.dumps(redactions or []))
        session.add(record); await session.commit(); return record
    async def list(self,session:AsyncSession,project_id:str):
        from sqlalchemy import select
        return (await session.execute(select(ContextPackRecord).where(ContextPackRecord.project_id==project_id).order_by(ContextPackRecord.generated_at.desc()))).scalars().all()
    def inspect(self,pack:ContextPackRecord):
        payload=pack.to_dict(); payload["content_included"]=False; payload["inspection_scope"]="manifest_only"; return payload
    def freshness(self,pack:ContextPackRecord,current:Dict[str,Dict[str,str|None]]):
        stale=[]
        for source in json.loads(pack.manifest_json):
            now=current.get(source["source_id"])
            if not now: stale.append({"source_id":source["source_id"],"reason":"source_missing"})
            elif now.get("version")!=source["version"]: stale.append({"source_id":source["source_id"],"reason":"version_changed","was":source["version"],"current":now.get("version")})
            elif source.get("content_hash") and now.get("content_hash")!=source["content_hash"]: stale.append({"source_id":source["source_id"],"reason":"hash_changed"})
        return {"reproducible":not stale,"stale":bool(stale),"stale_sources":stale,"checked_sources":len(json.loads(pack.manifest_json))}

context_pack_service=ContextPackService()
