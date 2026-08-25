import unittest
from datetime import datetime, timedelta

from core.ai_fleet.errors import DomainError
from core.ai_fleet.providers import (
    PROVIDER_PROTOCOL_VERSION,
    ProviderAdapter,
    ProviderCapability,
    ProviderHealthObservation,
    ProviderHealthState,
    ProviderQuotaObservation,
    validate_adapter,
)


class HealthOnlyAdapter(ProviderAdapter):
    adapter_id = "health-only"
    capabilities = frozenset({ProviderCapability.HEALTH})

    async def health(self):
        now = datetime.utcnow()
        return ProviderHealthObservation(ProviderHealthState.HEALTHY, now, now + timedelta(seconds=30), {"source": "test"})


class ProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_capabilities_are_explicit_and_unsupported_operations_fail(self):
        adapter = HealthOnlyAdapter()
        validate_adapter(adapter)
        self.assertTrue(adapter.supports(ProviderCapability.HEALTH))
        self.assertFalse(adapter.supports(ProviderCapability.LIST_MODELS))
        observation = await adapter.health()
        self.assertEqual(observation.state, ProviderHealthState.HEALTHY)
        with self.assertRaises(DomainError):
            await adapter.list_models()

    async def test_quota_observation_preserves_unknowns(self):
        observation = ProviderQuotaObservation(checked_at=datetime.utcnow(), scope="monthly")
        self.assertIsNone(observation.limit)
        self.assertIsNone(observation.remaining)
        self.assertIsNone(observation.resets_at)
        self.assertEqual(observation.unit, "unknown")

    async def test_protocol_and_streaming_contract_validation(self):
        class BadVersion(HealthOnlyAdapter):
            protocol_version = "2.0"

        class StreamWithoutExecute(ProviderAdapter):
            adapter_id = "bad-stream"
            capabilities = frozenset({ProviderCapability.STREAM})

        with self.assertRaises(ValueError):
            validate_adapter(BadVersion())
        with self.assertRaises(ValueError):
            validate_adapter(StreamWithoutExecute())
        self.assertEqual(HealthOnlyAdapter.protocol_version, PROVIDER_PROTOCOL_VERSION)


if __name__ == "__main__":
    unittest.main()
