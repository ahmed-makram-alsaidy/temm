import hashlib,uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from ..storage.models import ResearchCitationRecord,ResearchClaimRecord,ResearchQueryRecord,ResearchSourceRecord
class ResearchClaimService:
 async def create(self,s:AsyncSession,query_id:str,statement:str,requirement_id=None):
  query=await s.get(ResearchQueryRecord,query_id)
  if not query or not statement.strip(): raise DomainError("validation_failed",message="Research claim is invalid.")
  claim=ResearchClaimRecord(id=f"claim-{uuid.uuid4().hex[:12]}",query_id=query_id,project_id=query.project_id,requirement_id=requirement_id,statement=statement.strip(),status="unsupported"); s.add(claim); await s.commit(); return claim
 async def cite(self,s:AsyncSession,claim_id:str,source_id:str,excerpt:str,locator=None):
  claim=await s.get(ResearchClaimRecord,claim_id); source=await s.get(ResearchSourceRecord,source_id)
  if not claim or not source or source.query_id!=claim.query_id or not excerpt.strip() or len(excerpt)>10000: raise DomainError("validation_failed",message="Research citation is invalid.")
  digest=hashlib.sha256(excerpt.encode()).hexdigest(); existing=(await s.execute(select(ResearchCitationRecord).where(ResearchCitationRecord.claim_id==claim_id,ResearchCitationRecord.source_id==source_id,ResearchCitationRecord.excerpt_hash==digest))).scalar_one_or_none()
  if existing:return existing
  citation=ResearchCitationRecord(id=f"citation-{uuid.uuid4().hex[:12]}",claim_id=claim_id,source_id=source_id,excerpt=excerpt,excerpt_hash=digest,locator=locator); s.add(citation); claim.status="supported"; await s.commit(); return citation
research_claim_service=ResearchClaimService()
