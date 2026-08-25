import unittest

from core.ai_fleet.judges import BlindCandidate, JudgeProvenance, JudgeRequest, JudgeResult, JudgeType


class JudgeContractTests(unittest.TestCase):
    def test_public_payload_hides_source_identities(self):
        request = JudgeRequest(request_id="judge-1", judge_type=JudgeType.MODEL, criteria=["correctness"], candidates=[BlindCandidate("candidate-a", "response A"), BlindCandidate("candidate-b", "response B")], private_identity_map={"candidate-a": {"run_id": "secret-run-a", "model_id": "secret-model-a"}, "candidate-b": {"run_id": "secret-run-b"}})
        payload = request.public_payload()
        self.assertNotIn("private_identity_map", payload)
        self.assertNotIn("secret-model-a", str(payload))
        self.assertEqual([item["candidate_id"] for item in payload["candidates"]], ["candidate-a", "candidate-b"])

    def test_result_is_opinion_not_ground_truth(self):
        result = JudgeResult(request_id="judge-1", judge_type=JudgeType.MODEL, provenance=JudgeProvenance.MODEL_OPINION, winner_candidate_id="candidate-a", scores={"candidate-a": 90, "candidate-b": 70}, rationale="Candidate A better satisfies the criterion.", confidence=0.8, method="blind_pairwise_v1").validate(["candidate-a", "candidate-b"])
        payload = result.to_dict()
        self.assertFalse(payload["ground_truth"])
        self.assertEqual(payload["provenance"], "model_opinion")
        self.assertEqual(payload["confidence"], 0.8)

    def test_invalid_provenance_confidence_scores_and_identity_are_rejected(self):
        with self.assertRaises(ValueError):
            JudgeResult("j", JudgeType.MODEL, JudgeProvenance.EXECUTED_TEST, None, {}, "reason", 0.5, "m").validate(["a"])
        with self.assertRaises(ValueError):
            JudgeResult("j", JudgeType.HUMAN, JudgeProvenance.HUMAN_PREFERENCE, "missing", {"a": 101}, "reason", 1.1, "m").validate(["a"])
        with self.assertRaises(ValueError):
            JudgeRequest("j", JudgeType.RULE, ["x"], [BlindCandidate("a", "one"), BlindCandidate("a", "two")]).validate()


if __name__ == "__main__":
    unittest.main()
