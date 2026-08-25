from typing import Any,Dict,List
class CompletenessAuditService:
 def aggregate(self,rule_results:List[Dict[str,Any]],gate_results:List[Dict[str,Any]],dod_results:List[Dict[str,Any]]):
  findings=[]
  for result in rule_results+gate_results:findings.extend(result.get("findings",[]))
  blocking=[item for item in findings if item.get("severity") in {"critical","high"} and item.get("status","open") not in {"resolved","waived"}]
  unknown=[item for item in findings if item.get("severity") in {"critical","high"} and item.get("status","open") not in {"resolved","waived"} and (item.get("evidence") is None or item.get("evidence")=="unknown")]
  incomplete=[item for item in dod_results if not item.get("done")]
  advisory=[item for item in findings if item not in blocking]
  ready=not blocking and not unknown and not incomplete
  return {"ready":ready,"blocking_findings":blocking,"unknown_blocking_evidence":unknown,"incomplete_tasks":incomplete,"advisory_findings":advisory,"aggregate_score_override_allowed":False,"audit_version":"1.0","explanation":"Ready requires zero unresolved blocking findings, zero unknown blocking evidence, and all task definitions of done satisfied."}
completeness_audit_service=CompletenessAuditService()
