import unittest

from sqlalchemy import delete

from core.ai_fleet.services.run_output import MAX_CHUNK_BYTES, MAX_RUN_OUTPUT_BYTES, RunOutputService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import RunOutputChunkRecord
from core.ai_fleet.storage.secret_vault import secret_vault


class RunOutputPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.run_id = f"output-run-{id(self)}"
        self.service = RunOutputService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id == self.run_id))
            await session.commit()

    async def test_redaction_order_and_cursor(self):
        secret = "output-secret-820394"
        secret_vault.set_key("output-test", secret)
        try:
            async with AsyncSessionLocal() as session:
                one = await self.service.append(session, self.run_id, "stdout", f"value={secret}")
                two = await self.service.append(session, self.run_id, "stderr", "safe")
                await session.commit()
                replay = await self.service.list(session, self.run_id, after_sequence=one.sequence)
            self.assertNotIn(secret, one.content)
            self.assertIn("[REDACTED]", one.content)
            self.assertEqual([item.id for item in replay], [two.id])
        finally:
            secret_vault.delete_key("output-test")

    async def test_chunk_and_total_output_are_bounded(self):
        async with AsyncSessionLocal() as session:
            first = await self.service.append(session, self.run_id, "stdout", "x" * (MAX_CHUNK_BYTES + 100))
            self.assertTrue(first.truncated)
            self.assertLessEqual(first.byte_count, MAX_CHUNK_BYTES)
            for _ in range((MAX_RUN_OUTPUT_BYTES // MAX_CHUNK_BYTES) + 2):
                await self.service.append(session, self.run_id, "stdout", "y" * MAX_CHUNK_BYTES)
            await session.commit()
            rows = await self.service.list(session, self.run_id, limit=500)
        self.assertLessEqual(sum(row.byte_count for row in rows), MAX_RUN_OUTPUT_BYTES)
        self.assertTrue(any(row.truncated for row in rows))


if __name__ == "__main__":
    unittest.main()
