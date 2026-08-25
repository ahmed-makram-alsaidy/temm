import asyncio
from typing import Awaitable,Callable,Dict,List
class WorkflowParallelService:
 async def execute(self,branches:List[str],runner:Callable[[str],Awaitable[dict]],join_policy:str="all",quorum:int|None=None,control:Dict[str,bool]|None=None):
  if join_policy not in {"all","any","quorum"} or join_policy=="quorum" and (not quorum or not 1<=quorum<=len(branches)):raise ValueError("Join policy is invalid.")
  async def one(branch):
   if (control or {}).get("cancelled"):return {"branch":branch,"status":"cancelled"}
   try:return {"branch":branch,**await runner(branch)}
   except Exception as exc:return {"branch":branch,"status":"failed","error":type(exc).__name__}
  results=await asyncio.gather(*(one(branch) for branch in branches));completed=sum(x.get("status")=="completed" for x in results)
  success=completed==len(branches) if join_policy=="all" else completed>=1 if join_policy=="any" else completed>=quorum
  return {"status":"completed" if success else "failed","join_policy":join_policy,"quorum":quorum,"results":results,"completed_branches":completed,"failed_branches":len(branches)-completed,"partial_failure":0<completed<len(branches),"cancelled":bool((control or {}).get("cancelled"))}
workflow_parallel_service=WorkflowParallelService()
