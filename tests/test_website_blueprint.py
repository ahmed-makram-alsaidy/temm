import unittest

from core.ai_fleet.website_blueprint import WEBSITE_TEMPLATE


class WebsiteBlueprintTests(unittest.TestCase):
    def test_covers_canonical_website_concerns_without_stack_prescription(self):
        payload = WEBSITE_TEMPLATE.to_dict()
        section_ids = {section["section_id"] for section in payload["sections"]}
        self.assertEqual(section_ids, {"outcomes", "content", "experience", "discoverability", "performance", "security", "integrations", "delivery"})
        gate_types = {gate["gate_type"] for section in payload["sections"] for gate in section["gates"]}
        self.assertTrue({"accessibility", "performance", "security", "deployment"} <= gate_types)
        serialized = str(payload).lower()
        for stack in ["react", "vue", "angular", "next.js", "django", "laravel"]: self.assertNotIn(stack, serialized)
        self.assertEqual(payload["metadata"]["stack_policy"], "implementation_stack_not_prescribed")

    def test_network_sections_are_conditional(self):
        payload = WEBSITE_TEMPLATE.to_dict(); sections = {item["section_id"]: item for item in payload["sections"]}
        self.assertEqual(sections["security"]["condition"], {"capability": "network", "equals": True})
        self.assertEqual(sections["integrations"]["condition"], {"capability": "network", "equals": True})


if __name__ == "__main__": unittest.main()
