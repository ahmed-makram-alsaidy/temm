import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.services.judge_consensus import JudgeConsensusService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import JudgeConsensusRecord, JudgeExecutionRecord


class JudgeConsensusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.request_ids = [f"consensus-{id(self)}", f"tie-{id(self)}"]
        self.execution_ids = []
        async with AsyncSessionLocal() as session:
            for index, winner in enumerate(["a", "a", "b"]):
                record = JudgeExecutionRecord(id=f"judge-{id(self)}-{index}", request_id=self.request_ids[0], judge_type="model", provider=f"p{index}", model_id=f"m{index}", status="completed", provenance="model_opinion", result_json=json.dumps({"winner_candidate_id": winner, "confidence": 0.8, "ground_truth": False}))
                self.execution_ids.append(record.id); session.add(record)
            for index, winner in enumerate(["a", "b"]):
                record = JudgeExecutionRecord(id=f"tie-judge-{id(self)}-{index}", request_id=self.request_ids[1], judge_type="model", provider=f"p{index}", model_id=f"m{index}", status="completed", provenance="model_opinion", result_json=json.dumps({"winner_candidate_id": winner, "confidence": 0.5, "ground_truth": False}))
                self.execution_ids.append(record.id); session.add(record)
            failed = JudgeExecutionRecord(id=f"failed-{id(self)}", request_id=self.request_ids[0], judge_type="model", status="failed", provenance="model_opinion", result_json="{}")
            self.execution_ids.append(failed.id); session.add(failed)
            await session.commit()
        self.consensus_ids = []
        self.service = JudgeConsensusService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.consensus_ids: await session.execute(delete(JudgeConsensusRecord).where(JudgeConsensusRecord.id.in_(self.consensus_ids)))
            await session.execute(delete(JudgeExecutionRecord).where(JudgeExecutionRecord.id.in_(self.execution_ids)))
            await session.commit()

    async def test_majority_algorithm_persists_disagreement(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.aggregate(session, self.request_ids[0], 2 / 3)
            self.consensus_ids.append(result.id)
        payload = result.to_dict()
        self.assertEqual(result.status, "consensus")
        self.assertEqual(result.winner_candidate_id, "a")
        self.assertEqual(result.algorithm, "majority-v1")
        self.assertAlmostEqual(result.agreement, 2 / 3)
        self.assertEqual(payload["result"]["judge_count"], 3)
        self.assertFalse(payload["result"]["ground_truth"])

    async def test_tie_requires_escalation(self):
        async with AsyncSessionLocal() as session:
            result = await self.service.aggregate(session, self.request_ids[1])
            self.consensus_ids.append(result.id)
        self.assertEqual(result.status, "escalation_required")
        self.assertIsNone(result.winner_candidate_id)
        self.assertEqual(result.to_dict()["result"]["escalation_reason"], "tie")

    async def test_invalid_threshold_is_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception): await self.service.aggregate(session, self.request_ids[0], 0.5)


if __name__ == "__main__":
    unittest.main()
