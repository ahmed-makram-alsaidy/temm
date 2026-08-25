from typing import Any,Dict,List
class ReadinessReportService:
 def generate(self,deliverable:Dict[str,Any],audit:Dict[str,Any],checks:List[Dict[str,Any]]):
  sections={"completed":[],"failed":[],"waived":[],"unknown":[]}
  for check in checks:
   status=check.get("status","unknown");bucket="completed" if status=="passed" else "failed" if status=="failed" else "waived" if status=="waived" else "unknown";sections[bucket].append(check)
  ready=bool(audit.get("ready")) and not sections["failed"] and not sections["unknown"]
  return {"deliverable_id":deliverable["id"],"deliverable_version":deliverable["version"],"ready":ready,"deployment_ready":ready,"success_claim":ready,"sections":sections,"blocking_findings":audit.get("blocking_findings",[]),"trace":{"requirement_ids":deliverable.get("requirement_ids",[]),"asset_ids":deliverable.get("asset_ids",[]),"run_ids":deliverable.get("run_ids",[]),"gate_ids":deliverable.get("gate_ids",[])},"report_version":"1.0","statement":"Evidence supports readiness." if ready else "Readiness is not established; unresolved or unknown evidence remains."}
readiness_report_service=ReadinessReportService()
