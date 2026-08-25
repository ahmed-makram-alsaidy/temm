import json
import unittest
from sqlalchemy import delete
from core.ai_fleet.services.decisions import DecisionService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectDecisionRecord, ProjectRecord

class DecisionContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project=f"decision-context-{id(self)}"; self.ids=[f"dc-{id(self)}-{i}" for i in range(5)]
        async with AsyncSessionLocal() as s:
            s.add(ProjectRecord(id=self.project,name="Context",slug=f"context-{id(self)}",project_type="software",owner="local"))
            data=[("project",None,"approved"),("component","billing","approved"),("component","other","approved"),("requirement","req-1","approved"),("project",None,"superseded")]
            for i,(scope,scope_id,status) in enumerate(data): s.add(ProjectDecisionRecord(id=self.ids[i],project_id=self.project,scope_type=scope,scope_id=scope_id,statement=str(i),rationale="r",impact="i",rule_json=json.dumps({}),source_type="user",status=status))
            await s.commit()
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as s: await s.execute(delete(ProjectDecisionRecord).where(ProjectDecisionRecord.id.in_(self.ids))); await s.execute(delete(ProjectRecord).where(ProjectRecord.id==self.project)); await s.commit()
    async def test_active_scope_selection_is_traceable(self):
        async with AsyncSessionLocal() as s: result=await DecisionService().context(s,self.project,"billing",["req-1"])
        self.assertEqual([x["reason"] for x in result["selected"]],["project_scope","component_scope","requirement_scope"]); self.assertEqual({x["decision_id"]:x["reason"] for x in result["excluded"]},{self.ids[2]:"scope_not_relevant",self.ids[4]:"status_superseded"}); self.assertEqual(result["selector_version"],"1.0")

if __name__=="__main__": unittest.main()
