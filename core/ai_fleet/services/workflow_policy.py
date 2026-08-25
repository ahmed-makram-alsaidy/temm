from typing import Any,Dict
class WorkflowPolicyService:
 def condition(self,condition:Dict[str,Any],values:Dict[str,Any]):
  op=condition.get("operator","always")
  if op=="always":return True
  value=values.get(condition.get("field"))
  if op=="equals":return value==condition.get("value")
  if op=="in":return value in condition.get("values",[])
  if op=="exists":return (condition.get("field") in values)==bool(condition.get("value",True))
  raise ValueError("Unsupported workflow condition.")
 def retry(self,attempt:int,error_code:str|None,policy:Dict[str,Any]):
  maximum=int(policy.get("max_attempts",1));retryable=set(policy.get("retryable_errors",[]));base=float(policy.get("backoff_seconds",0));cap=float(policy.get("max_backoff_seconds",60))
  if not 1<=maximum<=10 or base<0 or cap<base:raise ValueError("Workflow retry policy is invalid.")
  should=attempt<maximum and error_code in retryable;delay=min(base*(2**max(attempt-1,0)),cap) if should else 0
  return {"attempt":attempt,"max_attempts":maximum,"error_code":error_code,"decision":"retry" if should else "terminal","backoff_seconds":delay,"policy_version":"1.0"}
workflow_policy_service=WorkflowPolicyService()
