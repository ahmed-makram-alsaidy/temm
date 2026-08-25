import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.run_output import RunOutputService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ArenaSessionRecord, RunOutputChunkRecord, TaskRun


class BlindArenaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_ids = [f"arena-run-{id(self)}-{index}" for index in range(2)]
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=self.run_ids[0], prompt="same prompt", status="completed", selected_agent_id="agent-one"))
            session.add(TaskRun(id=self.run_ids[1], prompt="same prompt", status="completed", selected_model_id="model-two"))
            await session.commit()
            await RunOutputService().append(session, self.run_ids[0], "stdout", "REAL RESPONSE ONE")
            await RunOutputService().append(session, self.run_ids[1], "output", "REAL RESPONSE TWO")
            await session.commit()
        self.arena_id = None
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.arena_id: await session.execute(delete(ArenaSessionRecord).where(ArenaSessionRecord.id == self.arena_id))
            await session.execute(delete(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id.in_(self.run_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            await session.commit()

    async def test_identities_are_hidden_until_single_vote(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/arena/sessions", json={"run_a_id": self.run_ids[0], "run_b_id": self.run_ids[1]})
            self.assertEqual(created.status_code, 200, created.text)
            self.arena_id = created.json()["arena_id"]
            before = created.json()
            loaded = await client.get(f"/api/arena/sessions/{self.arena_id}")
            voted = await client.post(f"/api/arena/sessions/{self.arena_id}/vote", json={"winner": "a"})
            repeated = await client.post(f"/api/arena/sessions/{self.arena_id}/vote", json={"winner": "b"})
        self.assertFalse(before["identities_revealed"])
        self.assertNotIn("identity_a", before)
        self.assertIn(before["response_a"], {"REAL RESPONSE ONE", "REAL RESPONSE TWO"})
        self.assertFalse(loaded.json()["identities_revealed"])
        self.assertTrue(voted.json()["identities_revealed"])
        self.assertIn(voted.json()["identity_a"]["run_id"], self.run_ids)
        self.assertEqual(repeated.status_code, 409)

    async def test_mismatched_or_nonterminal_runs_are_rejected(self):
        async with AsyncSessionLocal() as session:
            second = await session.get(TaskRun, self.run_ids[1]); second.prompt = "different"; await session.commit()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.post("/api/arena/sessions", json={"run_a_id": self.run_ids[0], "run_b_id": self.run_ids[1]})
            legacy = await client.post("/api/arena/vote")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(legacy.status_code, 410)


if __name__ == "__main__":
    unittest.main()
