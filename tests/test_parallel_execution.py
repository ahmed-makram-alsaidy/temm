import asyncio,unittest
from core.ai_fleet.services.parallel_execution import ParallelExecutionService
class ParallelExecutionTests(unittest.IsolatedAsyncioTestCase):
 async def test_conflicting_writes_serialize_and_independent_writes_overlap(self):
  service=ParallelExecutionService();active={};conflict=False;maximum=0;total=0
  async def execute(task):
   nonlocal conflict,maximum,total
   path=task["write_paths"][0];active[path]=active.get(path,0)+1;total+=1;maximum=max(maximum,total);conflict=conflict or active[path]>1;await asyncio.sleep(.03);active[path]-=1;total-=1;return {"status":"done"}
  tasks=[{"task_id":"a","workspace_id":"w","write_paths":["same.txt"]},{"task_id":"b","workspace_id":"w","write_paths":["same.txt"]},{"task_id":"c","workspace_id":"w","write_paths":["other.txt"]}]
  result=await service.run(tasks,execute);self.assertFalse(conflict);self.assertGreaterEqual(maximum,2);self.assertEqual(len(result),3)
 async def test_traversal_path_is_rejected(self):
  async def execute(task):return {}
  with self.assertRaises(ValueError):await ParallelExecutionService().run([{"task_id":"a","workspace_id":"w","write_paths":["../x"]}],execute)
if __name__=="__main__":unittest.main()
