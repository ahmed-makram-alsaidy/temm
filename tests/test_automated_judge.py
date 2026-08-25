import json
import unittest

from sqlalchemy import delete

from core.ai_fleet.judges import BlindCandidate, JudgeRequest, JudgeType
from core.ai_fleet.providers import ProviderStreamEvent
from core.ai_fleet.services.automated_judge import AutomatedJudgeService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import JudgeExecutionRecord


class FakeAdapter:
    def __init__(self, output):
        self.output = output
        self.prompt = ""
    async def stream(self, model_id, prompt, request_id):
        self.prompt = prompt
        yield ProviderStreamEvent("chunk", self.output)
        yield ProviderStreamEvent("done")


class FakeRegistry:
    def __init__(self, adapter): self.adapter = adapter
    def resolve(self, provider): return self.adapter


class AutomatedJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.ids = []
        self.request = JudgeRequest("judge-request", JudgeType.MODEL, ["correctness"], [BlindCandidate("candidate-a", "A"), BlindCandidate("candidate-b", "B")], private_identity_map={"candidate-a": {"model_id": "SECRET-MODEL"}})

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(JudgeExecutionRecord).where(JudgeExecutionRecord.id.in_(self.ids)))
                await session.commit()

    async def test_real_adapter_output_is_validated_and_persisted_blind(self):
        adapter = FakeAdapter(json.dumps({"winner_candidate_id": "candidate-a", "scores": {"candidate-a": 90, "candidate-b": 70}, "rationale": "A follows the criterion.", "confidence": 0.75}))
        async with AsyncSessionLocal() as session:
            record = await AutomatedJudgeService(FakeRegistry(adapter)).execute(session, self.request, "test-provider", "judge-model")
            self.ids.append(record.id)
        self.assertEqual(record.status, "completed")
        self.assertFalse(record.to_dict()["result"]["ground_truth"])
        self.assertEqual(record.to_dict()["result"]["provenance"], "model_opinion")
        self.assertNotIn("SECRET-MODEL", adapter.prompt)
        self.assertEqual(len(record.raw_output_hash), 64)

    async def test_malformed_or_identity_invalid_output_is_recorded_failed(self):
        for output in ["not json", json.dumps({"winner_candidate_id": "unknown", "scores": {}, "rationale": "x", "confidence": 0.5})]:
            async with AsyncSessionLocal() as session:
                record = await AutomatedJudgeService(FakeRegistry(FakeAdapter(output))).execute(session, self.request, "test-provider", "judge-model")
                self.ids.append(record.id)
            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error_code, "invalid_judge_output")
            self.assertFalse(record.to_dict()["result"]["ground_truth"])


if __name__ == "__main__":
    unittest.main()
