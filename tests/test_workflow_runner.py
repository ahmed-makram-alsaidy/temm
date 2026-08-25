import unittest
from core.ai_fleet.services.workflow_runner import WorkflowRunnerService
from core.ai_fleet.workflow_contract import WorkflowDefinition,WorkflowEdge,WorkflowPort
from core.ai_fleet.workflow_nodes import build_node
class WorkflowRunnerTests(unittest.IsolatedAsyncioTestCase):
 def definition(self):
  a=build_node("task","task");b=build_node("output","output");return WorkflowDefinition("w","1",[a,b],[WorkflowEdge("task","task","output","value")],[WorkflowPort("goal","text")],[WorkflowPort("result","any")])
 async def test_real_evidence_flows_through_dag(self):
  async def executor(node_id,node_type,inputs):return {"status":"completed","outputs":{"task":{"goal":inputs.get("goal")} if node_id=="task" else None,"result":inputs.get("value")},"evidence":{"run_id":f"run-{node_id}"}}
  result=await WorkflowRunnerService().run(self.definition(),{"goal":"build"},executor,{})
  self.assertEqual(result["status"],"completed");self.assertFalse(result["simulated"]);self.assertEqual([x["node_id"] for x in result["events"]],["task","output"])
 async def test_failure_and_cancellation_never_simulate_completion(self):
  async def failed(node_id,node_type,inputs):return {"status":"failed","outputs":{},"evidence":{"run_id":"run-failed"}}
  self.assertEqual((await WorkflowRunnerService().run(self.definition(),{},failed,{}))["status"],"failed")
  self.assertEqual((await WorkflowRunnerService().run(self.definition(),{},failed,{"cancelled":True}))["status"],"cancelled")
 async def test_missing_evidence_is_rejected(self):
  async def invalid(a,b,c):return {"status":"completed","outputs":{}}
  with self.assertRaises(Exception):await WorkflowRunnerService().run(self.definition(),{},invalid,{})
if __name__=="__main__":unittest.main()
