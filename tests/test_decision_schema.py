import json
import unittest
from datetime import datetime

from sqlalchemy import delete, select

from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProjectDecisionRecord, ProjectDecisionRevisionRecord, ProjectRecord


class DecisionSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): await init_db(); self.project_id = f"decision-project-{id(self)}"; self.decision_ids = [f"decision-{id(self)}-{i}" for i in range(2)]
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectDecisionRevisionRecord).where(ProjectDecisionRevisionRecord.decision_id.in_(self.decision_ids))); await session.execute(delete(ProjectDecisionRecord).where(ProjectDecisionRecord.id.in_(self.decision_ids))); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_active_decisions_are_queryable_by_scope(self):
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Decision", slug=f"decision-{id(self)}", project_type="software", owner="local"))
            session.add(ProjectDecisionRecord(id=self.decision_ids[0], project_id=self.project_id, scope_type="component", scope_id="database", statement="Use SQLite", rationale="Local first", impact="No setup", rule_json=json.dumps({"database": "sqlite"}), source_type="user", source_id="owner", status="approved", approved_by="owner", approved_at=datetime.utcnow()))
            session.add(ProjectDecisionRecord(id=self.decision_ids[1], project_id=self.project_id, scope_type="project", statement="Old decision", rationale="Old", impact="Old", rule_json="{}", source_type="import", status="superseded", supersedes_id=None))
            await session.commit()
            rows = (await session.execute(select(ProjectDecisionRecord).where(ProjectDecisionRecord.project_id == self.project_id, ProjectDecisionRecord.scope_type == "component", ProjectDecisionRecord.scope_id == "database", ProjectDecisionRecord.status == "approved"))).scalars().all()
        self.assertEqual(len(rows), 1); payload = rows[0].to_dict(); self.assertEqual(payload["rule"], {"database": "sqlite"}); self.assertEqual(payload["approved_by"], "owner"); self.assertEqual(payload["source_type"], "user")


if __name__ == "__main__": unittest.main()
