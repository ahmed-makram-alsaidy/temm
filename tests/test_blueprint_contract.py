import unittest

from core.ai_fleet.blueprints import BlueprintCondition, BlueprintGate, BlueprintQuestion, BlueprintSection, BlueprintTemplate


class BlueprintTemplateContractTests(unittest.TestCase):
    def valid(self):
        return BlueprintTemplate("software-base", "1.0", "software", ["coding", "quality_gate"], [BlueprintSection("foundation", "Foundation", ["functional", "constraint"], gates=[BlueprintGate("security-review", "security", True, "Security review required", BlueprintCondition("network", True))], questions=[BlueprintQuestion("deployment", "Where is it deployed?", "choice", True, ["local", "cloud"])])], {"schema_version": "1.0"})

    def test_versioned_extensible_contract_serializes_conditions(self):
        payload = self.valid().to_dict()
        self.assertEqual(payload["version"], "1.0")
        self.assertEqual(payload["sections"][0]["gates"][0]["condition"]["capability"], "network")
        self.assertTrue(payload["sections"][0]["gates"][0]["required"])
        self.assertEqual(payload["sections"][0]["questions"][0]["options"], ["local", "cloud"])

    def test_unknown_capabilities_duplicate_sections_and_invalid_questions_fail(self):
        with self.assertRaises(ValueError): BlueprintTemplate("x", "1", "software", ["magic"], self.valid().sections).validate()
        section = self.valid().sections[0]
        with self.assertRaises(ValueError): BlueprintTemplate("x", "1", "software", ["coding"], [section, section]).validate()
        bad = BlueprintSection("x", "X", ["functional"], questions=[BlueprintQuestion("q", "Q", "choice", True, [])])
        with self.assertRaises(ValueError): bad.validate()


if __name__ == "__main__": unittest.main()
