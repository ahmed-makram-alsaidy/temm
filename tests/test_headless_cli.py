import contextlib,io,json,unittest
import httpx
from sqlalchemy import delete
from aifleet import async_main
from core.ai_fleet.main import app
from core.ai_fleet.sdk import AiFleetClient
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AuditRecord,ProjectRecord
class HeadlessCliTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.client=AiFleetClient("http://test",httpx.ASGITransport(app=app));self.id=None
 async def asyncTearDown(self):
  await self.client.close()
  if self.id:
   async with AsyncSessionLocal() as s:await s.execute(delete(AuditRecord).where(AuditRecord.resource_id==self.id));await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.id));await s.commit()
 async def test_project_json_and_error_exit_codes(self):
  output=io.StringIO()
  with contextlib.redirect_stdout(output):code=await async_main(["--json","project","create","CLI",f"cli-{id(self)}","--goal","Publish a verified release note"],self.client)
  self.assertEqual(code,0);self.id=json.loads(output.getvalue())["id"]
  error=io.StringIO()
  with contextlib.redirect_stderr(error):code=await async_main(["--json","run","inspect","missing"],self.client)
  self.assertEqual(code,2);self.assertIn("run_not_found",error.getvalue())
 async def test_a_headless_create_without_a_goal_fails_deterministically(self):
  """A headless command may not prompt, may not invent a goal, and may not create a
  project without one. It reports the missing goal by name and exits non-zero."""
  for argv in [["--json","project","create","CLI",f"cli-none-{id(self)}"],["--json","project","create","CLI",f"cli-blank-{id(self)}","--goal","   "]]:
   error=io.StringIO();output=io.StringIO()
   with contextlib.redirect_stderr(error),contextlib.redirect_stdout(output):code=await async_main(argv,self.client)
   self.assertEqual(code,2,argv)
   self.assertEqual(json.loads(error.getvalue())["error"]["code"],"goal_required",argv)
   self.assertEqual(output.getvalue(),"","A refused create prints no project on stdout.")
  async with AsyncSessionLocal() as s:
   self.assertEqual([item.id for item in (await s.execute(__import__("sqlalchemy").select(ProjectRecord).where(ProjectRecord.name=="CLI"))).scalars().all()],[],"No project may be persisted without a goal.")
 async def test_a_missing_goal_is_reported_in_plain_text_mode_too(self):
  error=io.StringIO()
  with contextlib.redirect_stderr(error):code=await async_main(["project","create","CLI",f"cli-plain-{id(self)}"],self.client)
  self.assertEqual(code,2);self.assertIn("goal_required",error.getvalue())
 async def test_the_goal_reaches_the_persisted_project(self):
  output=io.StringIO()
  with contextlib.redirect_stdout(output):code=await async_main(["--json","project","create","CLI",f"cli-goal-{id(self)}","--goal","Ship a verified invoice export"],self.client)
  self.assertEqual(code,0);self.id=json.loads(output.getvalue())["id"]
  async with AsyncSessionLocal() as s:record=await s.get(ProjectRecord,self.id)
  self.assertEqual(record.purpose,"Ship a verified invoice export")
if __name__=="__main__":unittest.main()
