import unittest
from core.ai_fleet.workflow_contract import WorkflowDefinition,WorkflowEdge,WorkflowNode,WorkflowPort
class WorkflowContractTests(unittest.TestCase):
 def valid(self):
  out=WorkflowPort("out","text");inp=WorkflowPort("in","text");return WorkflowDefinition("w","1.0",[WorkflowNode("a","task",[],[out],["coding"],retry={"max_attempts":2}),WorkflowNode("b","output",[inp],[])],[WorkflowEdge("a","out","b","in",{"type":"always"})],[],[out])
 def test_valid_versioned_dag(self):self.assertEqual(self.valid().validate().version,"1.0")
 def test_cycle_unknown_capability_bad_port_and_retry_fail(self):
  value=self.valid();cycle=WorkflowDefinition(value.workflow_id,value.version,value.nodes,[*value.edges,WorkflowEdge("b","missing","a","missing")],[],[])
  with self.assertRaises(ValueError):cycle.validate()
  bad=WorkflowDefinition("w","1",[WorkflowNode("a","task",[],[],["magic"])],[],[],[])
  with self.assertRaises(ValueError):bad.validate()
  retry=WorkflowDefinition("w","1",[WorkflowNode("a","task",[],[],retry={"max_attempts":99})],[],[],[])
  with self.assertRaises(ValueError):retry.validate()
if __name__=="__main__":unittest.main()
