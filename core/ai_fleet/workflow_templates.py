from dataclasses import dataclass
from typing import Dict,List
from .workflow_contract import WorkflowDefinition,WorkflowEdge,WorkflowPort
from .workflow_nodes import build_node
@dataclass(frozen=True)
class WorkflowTemplate:
 template_id:str;version:str;definition:WorkflowDefinition;prerequisites:List[str];gate_ids:List[str]
 def validate(self):
  self.definition.validate()
  if not self.prerequisites or not self.gate_ids:raise ValueError("Workflow template prerequisites and gates are required.")
  return self
def _template(name,middle,gates,prerequisites):
 task=build_node("task","task");node=build_node("worker",middle);output=build_node("output","output")
 # Generic typed adapters use compatible synthetic ports solely at template contract level.
 node=type(node)(node.node_id,node.node_type,[WorkflowPort("task","task")],[WorkflowPort("value","any")],node.required_capabilities,node.permissions,node.retry)
 definition=WorkflowDefinition(name,"1.0",[task,node,output],[WorkflowEdge("task","task","worker","task"),WorkflowEdge("worker","value","output","value")],[],[WorkflowPort("result","any")])
 return WorkflowTemplate(name,"1.0",definition,prerequisites,gates).validate()
TEMPLATES:Dict[str,WorkflowTemplate]={
 "code-review":_template("code-review","agent",["tests","security"],["verified_coding_agent","approved_workspace"]),
 "feature":_template("feature","agent",["tests","build"],["approved_requirements","verified_coding_agent"]),
 "bug":_template("bug","agent",["tests"],["reproduction_evidence","verified_coding_agent"]),
 "security":_template("security","critic",["security"],["approved_workspace","security_capability"]),
 "research":_template("research","agent",["citation"],["approved_network_policy","research_connector"]),
 "compare":_template("compare","judge",["evidence"],["two_real_runs","judge_contract"]),
 "benchmark":_template("benchmark","gate",["benchmark"],["versioned_suite","verified_executor"]),
}
