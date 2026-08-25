from typing import Any,Awaitable,Callable,Dict
from ..errors import DomainError
from ..workflow_contract import WorkflowDefinition
Executor=Callable[[str,str,Dict[str,Any]],Awaitable[Dict[str,Any]]]
class WorkflowRunnerService:
 async def run(self,definition:WorkflowDefinition,inputs:Dict[str,Any],executor:Executor,control:Dict[str,bool]):
  definition.validate();by={n.node_id:n for n in definition.nodes};incoming={n.node_id:[] for n in definition.nodes};outgoing={n.node_id:[] for n in definition.nodes}
  for edge in definition.edges:incoming[edge.target_node].append(edge);outgoing[edge.source_node].append(edge)
  pending=set(by);results={};events=[]
  while pending:
   if control.get("cancelled"):return {"status":"cancelled","results":results,"events":events}
   ready=sorted(node for node in pending if all(edge.source_node in results for edge in incoming[node]))
   if not ready:raise DomainError("resource_conflict",message="Workflow cannot make progress.")
   for node_id in ready:
    if control.get("cancelled"):return {"status":"cancelled","results":results,"events":events}
    node=by[node_id];node_inputs=dict(inputs)
    for edge in incoming[node_id]:node_inputs[edge.target_port]=results[edge.source_node]["outputs"].get(edge.source_port)
    result=await executor(node_id,node.node_type,node_inputs)
    if not result.get("evidence") or result.get("status") not in {"completed","failed","cancelled"}:raise DomainError("validation_failed",message="Workflow node returned invalid real execution evidence.")
    results[node_id]=result;pending.remove(node_id);events.append({"node_id":node_id,"status":result["status"],"evidence":result["evidence"]})
    if result["status"]!="completed":return {"status":result["status"],"results":results,"events":events}
  return {"status":"completed","results":results,"events":events,"simulated":False}
workflow_runner_service=WorkflowRunnerService()
