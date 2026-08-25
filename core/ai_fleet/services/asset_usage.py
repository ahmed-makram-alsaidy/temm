import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import AssetRecord,AssetUsageRecord
class AssetUsageService:
 async def link(self,s:AsyncSession,asset_id,target_type,target_id,role,required=True):
  if not await s.get(AssetRecord,asset_id) or target_type not in {"component","requirement","task","deliverable"} or not target_id or not role:raise DomainError("validation_failed",message="Asset usage edge is invalid.")
  existing=(await s.execute(select(AssetUsageRecord).where(AssetUsageRecord.asset_id==asset_id,AssetUsageRecord.target_type==target_type,AssetUsageRecord.target_id==target_id,AssetUsageRecord.usage_role==role))).scalar_one_or_none()
  if existing:return existing
  record=AssetUsageRecord(id=f"asset-usage-{uuid.uuid4().hex[:12]}",asset_id=asset_id,target_type=target_type,target_id=target_id,usage_role=role,required=required);s.add(record);await s.commit();return record
 async def affected(self,s:AsyncSession,asset_id):
  rows=(await s.execute(select(AssetUsageRecord).where(AssetUsageRecord.asset_id==asset_id).order_by(AssetUsageRecord.target_type,AssetUsageRecord.target_id))).scalars().all();return {"asset_id":asset_id,"missing_asset_impact":[x.to_dict() for x in rows if x.required],"optional_usage":[x.to_dict() for x in rows if not x.required]}
asset_usage_service=AssetUsageService()
