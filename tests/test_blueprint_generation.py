import json
import unittest

from core.ai_fleet.business_blueprint import BUSINESS_SYSTEM_TEMPLATE
from core.ai_fleet.providers import ProviderStreamEvent
from core.ai_fleet.services.blueprint_generation import BlueprintGenerationService


class Adapter:
    def __init__(self, output=None, error=None): self.output = output; self.error = error
    async def stream(self, model, prompt, request):
        if self.error: yield ProviderStreamEvent("error", error_code=self.error)
        else: yield ProviderStreamEvent("chunk", self.output); yield ProviderStreamEvent("done")
class Registry:
    def __init__(self, adapter): self.adapter = adapter
    def resolve(self, provider): return self.adapter


class BlueprintGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_is_always_proposed_and_unapproved(self):
        output = json.dumps({"requirements": [{"section_id": "roles", "title": "Role matrix", "description": "Define permissions", "requirement_type": "security", "priority": "must", "acceptance": [{"statement": "Approved matrix"}], "status": "approved"}], "questions": [{"section_id": "data", "text": "Retention period?", "required": True}]})
        result = await BlueprintGenerationService(Registry(Adapter(output))).generate(BUSINESS_SYSTEM_TEMPLATE, "Build clinic system", {"owner": "clinic"}, "provider", "model")
        requirement = result["requirements"][0]
        self.assertEqual(requirement["status"], "proposed"); self.assertEqual(requirement["truth_state"], "proposed"); self.assertEqual(requirement["provenance"], "model_proposed"); self.assertFalse(requirement["approved"])
        self.assertTrue(result["approval_required"]); self.assertFalse(result["implementation_started"])

    async def test_malformed_unknown_section_and_provider_failure_are_rejected(self):
        for adapter in [Adapter("not json"), Adapter(json.dumps({"requirements": [{"section_id": "magic", "title": "x", "description": "x", "requirement_type": "x", "priority": "must", "acceptance": []}]})), Adapter(error="rate_limited")]:
            with self.assertRaises(Exception): await BlueprintGenerationService(Registry(adapter)).generate(BUSINESS_SYSTEM_TEMPLATE, "goal", {}, "provider", "model")


if __name__ == "__main__": unittest.main()
