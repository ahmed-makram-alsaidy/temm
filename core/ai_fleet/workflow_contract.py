from dataclasses import dataclass,field
from typing import Any,Dict,List
from .domain import CAPABILITIES
@dataclass(frozen=True)
class WorkflowPort: name:str;data_type:str;required:bool=True
@dataclass(frozen=True)
class WorkflowNode:
 node_id:str;node_type:str;inputs:List[WorkflowPort];outputs:List[WorkflowPort];required_capabilities:List[str]=field(default_factory=list);permissions:List[str]=field(default_factory=list);retry:Dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class WorkflowEdge: source_node:str;source_port:str;target_node:str;target_port:str;condition:Dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class WorkflowDefinition:
 workflow_id:str;version:str;nodes:List[WorkflowNode];edges:List[WorkflowEdge];inputs:List[WorkflowPort];outputs:List[WorkflowPort]
 def validate(self):
  ids=[n.node_id for n in self.nodes]
  if not self.workflow_id or not self.version or not ids or len(ids)!=len(set(ids)):raise ValueError("Workflow identity or nodes are invalid.")
  by={n.node_id:n for n in self.nodes}
  graph={x:[] for x in ids};indegree={x:0 for x in ids}
  for node in self.nodes:
   if set(node.required_capabilities)-set(CAPABILITIES):raise ValueError("Workflow capability is invalid.")
   attempts=node.retry.get("max_attempts",1)
   if not 1<=attempts<=10:raise ValueError("Workflow retry is invalid.")
  for edge in self.edges:
   if edge.source_node not in by or edge.target_node not in by or edge.source_port not in {x.name for x in by[edge.source_node].outputs} or edge.target_port not in {x.name for x in by[edge.target_node].inputs}:raise ValueError("Workflow edge is invalid.")
   graph[edge.source_node].append(edge.target_node);indegree[edge.target_node]+=1
  queue=sorted(x for x,d in indegree.items() if d==0);seen=[]
  while queue:
   node=queue.pop(0);seen.append(node)
   for target in sorted(graph[node]):indegree[target]-=1;queue.append(target) if indegree[target]==0 else None
  if len(seen)!=len(ids):raise ValueError("Workflow DAG contains a cycle.")
  return self
