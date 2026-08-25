import unittest

from core.ai_fleet.business_blueprint import BUSINESS_SYSTEM_TEMPLATE


class BusinessSystemBlueprintTests(unittest.TestCase):
    def test_covers_canonical_business_concerns(self):
        payload = BUSINESS_SYSTEM_TEMPLATE.to_dict(); sections = {item["section_id"]: item for item in payload["sections"]}
        self.assertEqual(set(sections), {"outcomes", "roles", "workflows", "data", "reports", "integrations", "operations", "quality"})
        gates = {gate["gate_id"] for section in sections.values() for gate in section["gates"]}
        self.assertTrue({"authorization-review", "backup-restore", "integration-failure", "deployment", "unit-tests", "security"} <= gates)
        self.assertEqual(sections["integrations"]["condition"], {"capability": "network", "equals": True})
        self.assertEqual(payload["metadata"]["stack_policy"], "implementation_stack_not_prescribed")

    def test_template_has_required_owner_role_workflow_data_and_acceptance_questions(self):
        ids = {question["question_id"] for section in BUSINESS_SYSTEM_TEMPLATE.to_dict()["sections"] for question in section["questions"]}
        self.assertTrue({"outcome", "role-matrix", "critical-workflows", "sensitive-data", "reports", "acceptance"} <= ids)


if __name__ == "__main__": unittest.main()
