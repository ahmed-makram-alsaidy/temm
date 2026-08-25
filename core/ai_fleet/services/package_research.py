from datetime import datetime
from typing import Any,Dict,List
from ..errors import DomainError

class PackageResearchService:
 def assess(self,package:str,registry:Dict[str,Any],docs:Dict[str,Any],security:Dict[str,Any],retrieved_at:datetime):
  if not package or not registry.get("source_url") or not docs.get("source_url") or not retrieved_at: raise DomainError("validation_failed",message="Package research requires current registry and documentation sources.")
  version=registry.get("latest_version");license_id=registry.get("license");advisories=security.get("advisories")
  evidence=[{"kind":"registry","url":registry["source_url"],"retrieved_at":retrieved_at.isoformat(),"version":version,"license":license_id},{"kind":"documentation","url":docs["source_url"],"retrieved_at":retrieved_at.isoformat(),"content_hash":docs.get("content_hash")},{"kind":"security","url":security.get("source_url"),"retrieved_at":retrieved_at.isoformat(),"advisory_count":len(advisories) if isinstance(advisories,list) else None}]
  missing=[name for name,value in [("version",version),("license",license_id),("security_advisories",advisories)] if value is None]
  return {"package":package,"version":version,"license":license_id,"advisories":advisories,"evidence":evidence,"recommendation_available":not missing,"recommendation":"eligible_for_review" if not missing else None,"missing_evidence":missing,"provenance":"retrieved_sources","as_of":retrieved_at.isoformat()}
package_research_service=PackageResearchService()
