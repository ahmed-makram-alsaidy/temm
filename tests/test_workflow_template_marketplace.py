import unittest

from core.ai_fleet.errors import DomainError
from core.ai_fleet.services.workflow_template_marketplace import WorkflowTemplateMarketplaceService


class WorkflowTemplateMarketplaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = WorkflowTemplateMarketplaceService()

    def payload(self):
        return {
            "schema_version": "1.0",
            "template_key": "market-review",
            "version": "1.0.0",
            "name": "Marketplace Review",
            "prerequisites": ["verified_coding_agent", "approved_workspace"],
            "gate_ids": ["tests", "security"],
            "executable": False,
            "definition": {
                "nodes": [
                    {"id": "task", "type": "task", "inputs": [], "outputs": [{"name": "task", "data_type": "task"}]},
                    {"id": "worker", "type": "agent", "inputs": [{"name": "task", "data_type": "task"}], "outputs": [{"name": "value", "data_type": "any"}], "required_capabilities": ["coding"], "permissions": ["file_read"], "retry": {"max_attempts": 2}},
                    {"id": "output", "type": "output", "inputs": [{"name": "value", "data_type": "any"}], "outputs": []},
                ],
                "edges": [
                    {"source_node": "task", "source_port": "task", "target_node": "worker", "target_port": "task"},
                    {"source_node": "worker", "source_port": "value", "target_node": "output", "target_port": "value"},
                ],
                "inputs": [],
                "outputs": [{"name": "result", "data_type": "any"}],
            },
        }

    def test_valid_template_remains_non_executable_with_visible_prerequisites(self):
        result = self.service.validate(self.payload())
        self.assertFalse(result["executable"])
        self.assertEqual(result["prerequisites"], ["verified_coding_agent", "approved_workspace"])
        self.assertEqual(result["gate_ids"], ["tests", "security"])
        self.assertEqual(result["definition"]["nodes"][1]["required_capabilities"], ["coding"])

    def test_executable_claim_missing_prerequisites_and_cycle_are_rejected(self):
        payload = self.payload()
        payload["executable"] = True
        with self.assertRaises(DomainError):
            self.service.validate(payload)
        payload = self.payload()
        payload["prerequisites"] = []
        with self.assertRaises(DomainError):
            self.service.validate(payload)
        payload = self.payload()
        payload["definition"]["edges"].append({"source_node": "output", "source_port": "missing", "target_node": "task", "target_port": "missing"})
        with self.assertRaises((DomainError, ValueError)):
            self.service.validate(payload)


if __name__ == "__main__":
    unittest.main()
