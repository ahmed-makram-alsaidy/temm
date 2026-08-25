import unittest

from core.ai_fleet.services.rule_evaluators import RuleEvaluatorService


class RuleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.service = RuleEvaluatorService()

    def test_exact_and_regex_are_reproducible(self):
        exact = self.service.evaluate("exact", "hello", {"expected": "hello"})
        regex = self.service.evaluate("regex", "ABC-123", {"pattern": r"[A-Z]+-\d+"})
        self.assertTrue(exact["passed"])
        self.assertEqual(exact["score"], 100.0)
        self.assertEqual(exact["evaluator_version"], "1.0")
        self.assertTrue(regex["passed"])
        self.assertEqual(regex["evidence"]["match_mode"], "fullmatch")

    def test_json_schema_subset_preserves_evidence(self):
        schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}}}}
        passed = self.service.evaluate("json_schema", '{"id":1,"tags":["a"]}', {"schema": schema})
        failed = self.service.evaluate("json_schema", '{"id":"1"}', {"schema": schema})
        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])
        self.assertEqual(passed["evidence"]["schema"], schema)

    def test_command_evaluators_require_real_receipt(self):
        receipt = {"task_id": "run-1", "outcome": "completed", "exit_code": 0, "error_code": None}
        for evaluator in ["unit_test", "build", "lint", "type_check"]:
            result = self.service.evaluate(evaluator, "", {}, receipt)
            self.assertTrue(result["passed"])
            self.assertEqual(result["evidence"]["execution_id"], "run-1")
        failed = self.service.evaluate("unit_test", "", {}, {**receipt, "outcome": "non_zero_exit", "exit_code": 1})
        self.assertFalse(failed["passed"])
        with self.assertRaises(Exception):
            self.service.evaluate("build", "", {})

    def test_invalid_and_oversized_inputs_are_rejected(self):
        with self.assertRaises(Exception):
            self.service.evaluate("regex", "x", {"pattern": "["})
        with self.assertRaises(Exception):
            self.service.evaluate("magic", "x", {})
        with self.assertRaises(Exception):
            self.service.evaluate("exact", "x" * (2 * 1024 * 1024 + 1), {"expected": "x"})


if __name__ == "__main__":
    unittest.main()
