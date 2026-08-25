import os
import unittest
import uuid
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.storage.database import AsyncSessionLocal, DB_PATH, assert_safe_database_path, init_db
from core.ai_fleet.storage.models import ProjectRecord


class DatabaseIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:8]
        self.owned_id = f"isolation-owned-{suffix}"
        self.unrelated_id = f"isolation-unrelated-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.owned_id, name="Owned fixture", slug=f"owned-{suffix}", project_type="software", owner="test"))
            session.add(ProjectRecord(id=self.unrelated_id, name="Unrelated fixture", slug=f"unrelated-{suffix}", project_type="software", owner="test"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id.in_([self.owned_id, self.unrelated_id])))
            await session.commit()

    def test_pytest_database_is_not_the_production_database(self):
        production = (Path.home() / ".ai_fleet" / "ai_fleet.db").resolve()
        self.assertEqual(os.environ.get("AI_FLEET_TEST_DATABASE"), "1")
        self.assertNotEqual(DB_PATH.resolve(), production)
        self.assertIn("ai-fleet-test-db-", str(DB_PATH.parent))

    def test_guard_refuses_production_database_in_test_mode(self):
        production = Path.home() / ".ai_fleet" / "ai_fleet.db"
        with self.assertRaisesRegex(RuntimeError, "production TEMM database"):
            assert_safe_database_path(production)

    async def test_scoped_teardown_cannot_delete_unrelated_project(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.owned_id))
            await session.commit()
            unrelated = await session.get(ProjectRecord, self.unrelated_id)
        self.assertIsNotNone(unrelated)


if __name__ == "__main__":
    unittest.main()
