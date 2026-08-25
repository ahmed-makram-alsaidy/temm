import unittest

import httpx

from core.ai_fleet.domain import CAPABILITIES, DOMAIN_DEFINITIONS, DomainKind, validate_capabilities
from core.ai_fleet.main import app


class DomainContractTests(unittest.TestCase):
    def test_domain_kinds_have_unique_nonempty_responsibilities(self):
        self.assertEqual(set(DOMAIN_DEFINITIONS), set(DomainKind))
        responsibilities = [definition.responsibility for definition in DOMAIN_DEFINITIONS.values()]
        self.assertTrue(all(responsibilities))
        self.assertEqual(len(responsibilities), len(set(responsibilities)))

    def test_agent_runtime_model_are_distinct(self):
        agent = DOMAIN_DEFINITIONS[DomainKind.AGENT]
        runtime = DOMAIN_DEFINITIONS[DomainKind.RUNTIME]
        model = DOMAIN_DEFINITIONS[DomainKind.MODEL]
        self.assertTrue(agent.may_execute)
        self.assertTrue(runtime.may_execute)
        self.assertFalse(model.may_execute)
        self.assertNotEqual(agent.responsibility, runtime.responsibility)
        self.assertNotEqual(runtime.responsibility, model.responsibility)

    def test_capability_validation_deduplicates_and_rejects_unknown(self):
        self.assertEqual(validate_capabilities(["coding", "coding", "shell"]), ["coding", "shell"])
        with self.assertRaises(ValueError):
            validate_capabilities(["coding", "imaginary"])
        self.assertIn("asset_search", CAPABILITIES)
        self.assertIn("quality_gate", CAPABILITIES)


class DomainContractApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_domain_contract_api_is_versioned(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/fleet/domain-contract")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["domain_schema_version"], "1.0")
        self.assertEqual(len(payload["domains"]), len(DomainKind))
        self.assertIn("coding", payload["capabilities"])


if __name__ == "__main__":
    unittest.main()
