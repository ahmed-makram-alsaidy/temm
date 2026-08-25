import unittest
from sqlalchemy import delete
from core.ai_fleet.services.project_learning import ProjectLearningService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectLearningConsentRecord, ProjectOutcomeRecord, ProjectRecord, TaskRun

class ProjectLearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id=f"learn-project-{id(self)}"; self.run_ids=[f"learn-run-{id(self)}-{i}" for i in range(3)]; self.service=ProjectLearningService()
        async with AsyncSessionLocal() as s:
            s.add(ProjectRecord(id=self.project_id,name="Learn",slug=f"learn-{id(self)}",project_type="software",owner="local"))
            for run_id in self.run_ids: s.add(TaskRun(id=run_id,prompt="x",project_id=self.project_id,status="completed"))
            await s.commit()
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as s: await s.execute(delete(ProjectOutcomeRecord).where(ProjectOutcomeRecord.project_id==self.project_id)); await s.execute(delete(ProjectLearningConsentRecord).where(ProjectLearningConsentRecord.project_id==self.project_id)); await s.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids))); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.project_id)); await s.commit()
    async def test_consent_required_and_recommendation_exposes_samples(self):
        async with AsyncSessionLocal() as s:
            with self.assertRaises(Exception): await self.service.record(s,self.project_id,self.run_ids[0],"react_debug","route-a","success",True,{})
            unavailable=await self.service.recommend(s,self.project_id,"react_debug"); await self.service.consent(s,self.project_id,True,"owner")
            await self.service.record(s,self.project_id,self.run_ids[0],"react_debug","route-a","success",True,{"source":"human"}); await self.service.record(s,self.project_id,self.run_ids[1],"react_debug","route-a","failure",False,{}); await self.service.record(s,self.project_id,self.run_ids[2],"react_debug","route-b","success",False,{})
            result=await self.service.recommend(s,self.project_id,"react_debug")
        self.assertEqual(unavailable["reason"],"consent_required"); self.assertEqual(result["sample_size"],3); self.assertEqual(result["recommendation"]["route_id"],"route-a"); self.assertEqual(result["recommendation"]["evidence_run_ids"],self.run_ids[:2]); self.assertTrue(result["consent"]["enabled"])

if __name__=="__main__": unittest.main()
