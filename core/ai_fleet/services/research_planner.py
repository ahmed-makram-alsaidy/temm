from typing import Any,Dict,List
class ResearchPlannerService:
 def plan(self,needs:List[Dict[str,Any]],allow_network:bool=False,allow_paid:bool=False,allow_private:bool=False):
  queries=[];skipped=[]
  for need in sorted(needs,key=lambda x:x["id"]):
   if need.get("state") not in {"open","in_progress"} or need.get("need_type") not in {"information","research","capability"}:continue
   policy=need.get("source_policy",{});requires_network=policy.get("network",True);paid=policy.get("paid",False);private=policy.get("private",False);approvals=[]
   if requires_network and not allow_network:approvals.append("network")
   if paid and not allow_paid:approvals.append("paid")
   if private and not allow_private:approvals.append("private")
   query={"query_id":f"research:{need['id']}","need_id":need["id"],"question":need.get("description") or need.get("title"),"query_kind":"factual_retrieval","max_sources":min(max(int(policy.get("max_sources",5)),1),20),"allowed_source_types":policy.get("allowed_source_types",["official_docs"]),"approval_required":approvals,"status":"blocked_approval" if approvals else "planned"}
   queries.append(query)
  return {"queries":queries,"skipped":skipped,"planner_version":"1.0","bounded":True}
research_planner_service=ResearchPlannerService()
