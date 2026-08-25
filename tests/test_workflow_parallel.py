import asyncio,unittest
from core.ai_fleet.services.workflow_parallel import WorkflowParallelService
class WorkflowParallelTests(unittest.IsolatedAsyncioTestCase):
 async def test_join_policies_and_partial_failures(self):
  async def runner(branch):await asyncio.sleep(.01);return {"status":"failed" if branch=="b" else "completed","evidence":{"branch":branch}}
  all_result=await WorkflowParallelService().execute(["a","b","c"],runner,"all");any_result=await WorkflowParallelService().execute(["a","b","c"],runner,"any");quorum=await WorkflowParallelService().execute(["a","b","c"],runner,"quorum",2)
  self.assertEqual(all_result["status"],"failed");self.assertTrue(all_result["partial_failure"]);self.assertEqual(any_result["status"],"completed");self.assertEqual(quorum["status"],"completed")
 async def test_cancellation_propagates_without_deadlock(self):
  async def runner(branch):return {"status":"completed"}
  result=await asyncio.wait_for(WorkflowParallelService().execute(["a","b"],runner,"all",control={"cancelled":True}),1);self.assertTrue(result["cancelled"]);self.assertTrue(all(x["status"]=="cancelled" for x in result["results"]))
if __name__=="__main__":unittest.main()
