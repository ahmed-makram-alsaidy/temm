from typing import Dict
from .workflow_contract import WorkflowNode,WorkflowPort
NODE_CONTRACTS:Dict[str,dict]={
 "task":{"inputs":[("goal","text")],"outputs":[("task","task")],"capabilities":[]},
 "classify":{"inputs":[("task","task")],"outputs":[("classification","classification")],"capabilities":["reasoning"]},
 "router":{"inputs":[("task","task")],"outputs":[("route","route")],"capabilities":["model_selection"]},
 "agent":{"inputs":[("task","task"),("route","route")],"outputs":[("run","run")],"capabilities":["streaming"]},
 "judge":{"inputs":[("candidates","runs")],"outputs":[("judgment","judgment")],"capabilities":["reasoning"]},
 "critic":{"inputs":[("artifact","artifact")],"outputs":[("critique","critique")],"capabilities":["reasoning"]},
 "gate":{"inputs":[("run","run")],"outputs":[("gate_result","gate_result")],"capabilities":["quality_gate"]},
 "approval":{"inputs":[("request","approval_request")],"outputs":[("decision","approval_decision")],"capabilities":[]},
 "output":{"inputs":[("value","any")],"outputs":[("result","any")],"capabilities":[]},
}
def build_node(node_id,node_type):
 contract=NODE_CONTRACTS.get(node_type)
 if not contract:raise ValueError("Unknown workflow node type.")
 return WorkflowNode(node_id,node_type,[WorkflowPort(n,t) for n,t in contract["inputs"]],[WorkflowPort(n,t) for n,t in contract["outputs"]],contract["capabilities"])
