from collections import defaultdict
from typing import Any, Dict, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..storage.models import AssetRecord

class AssetDuplicateService:
 async def detect(self,session:AsyncSession,project_id:str|None=None,perceptual:List[Dict[str,Any]]|None=None):
  statement=select(AssetRecord)
  if project_id: statement=statement.where(AssetRecord.project_id==project_id)
  rows=(await session.execute(statement)).scalars().all(); groups=defaultdict(list)
  for row in rows: groups[row.sha256].append(row)
  exact=[{"sha256":digest,"asset_ids":sorted(item.id for item in items),"count":len(items),"action":"review_required"} for digest,items in groups.items() if len(items)>1]
  exact.sort(key=lambda item:item["sha256"])
  candidates=[]
  known={row.id for row in rows}
  for item in perceptual or []:
   pair=sorted(item.get("asset_ids",[])); similarity=item.get("similarity")
   if len(pair)==2 and len(set(pair))==2 and set(pair)<=known and isinstance(similarity,(int,float)) and 0<=similarity<=1: candidates.append({"asset_ids":pair,"similarity":similarity,"method":item.get("method","external"),"action":"review_required"})
  candidates.sort(key=lambda item:(-item["similarity"],item["asset_ids"]))
  return {"exact_duplicates":exact,"perceptual_candidates":candidates,"assets_scanned":len(rows),"automatic_merge":False,"automatic_delete":False}
asset_duplicate_service=AssetDuplicateService()
