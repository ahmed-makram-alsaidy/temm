import asyncio
from contextlib import AsyncExitStack
from pathlib import PurePosixPath
from typing import Awaitable,Callable,Dict,List
class ParallelExecutionService:
 def __init__(self):self._locks:Dict[str,asyncio.Lock]={}
 async def run(self,tasks:List[dict],execute:Callable[[dict],Awaitable[dict]]):
  async def one(task):
   keys=sorted({f"{task['workspace_id']}:{self._normalize(path)}" for path in task.get("write_paths",[])})
   async with AsyncExitStack() as stack:
    for key in keys:await stack.enter_async_context(self._locks.setdefault(key,asyncio.Lock()))
    result=await execute(task);return {"task_id":task["task_id"],"lock_keys":keys,"result":result}
  return await asyncio.gather(*(one(task) for task in tasks))
 def _normalize(self,path):
  value=PurePosixPath(str(path).replace("\\","/"))
  if value.is_absolute() or ".." in value.parts:raise ValueError("Write path must be workspace-relative and traversal-free.")
  return value.as_posix()
parallel_execution_service=ParallelExecutionService()
