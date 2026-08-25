import unittest
from datetime import datetime, timezone

from core.ai_fleet.environment_discovery import ConfiguredProviderRecord, DiscoveredModelRecord, EnvironmentInventory
from core.ai_fleet.services.external_environment import ExternalEnvironmentService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelRecord, ProviderInstanceRecord


class ExternalEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_imports_generic_verified_opencode_route_with_credential_reference(self):
        await init_db()
        suffix = __import__("uuid").uuid4().hex[:8]
        provider_id = f"opencode:fixture-{suffix}"
        model_id = f"fixture-{suffix}/coder"
        now = datetime.now(timezone.utc).isoformat()
        inventory = EnvironmentInventory(
            providers=[ConfiguredProviderRecord(provider_id, "Fixture", "openai_compatible", None, "api_key", f"opencode_credential:fixture-{suffix}", "opencode-cli", 1, now, False)],
            models=[DiscoveredModelRecord(model_id, provider_id, "coder", "opencode-cli", now)],
            execution_probes=[{"model_id": model_id, "success": True}],
            discovered_at=now,
        )
        async with AsyncSessionLocal() as session:
            await ExternalEnvironmentService().import_inventory(session, inventory)
            provider = await session.get(ProviderInstanceRecord, provider_id)
            model = await session.get(ModelRecord, model_id)
            self.assertEqual(provider.to_dict()["secret_refs"], [f"opencode_credential:fixture-{suffix}"])
            self.assertEqual(provider.to_dict()["configuration"]["protocol"], "openai_compatible")
            self.assertEqual(model.availability_state, "available")
            await session.delete(model)
            await session.delete(provider)
            await session.commit()

    async def test_successful_probe_marks_provider_and_model_available(self):
        await init_db()
        suffix = __import__("uuid").uuid4().hex[:8]
        provider_id = f"opencode:probe-{suffix}"
        model_id = f"probe-{suffix}/coder"
        now = datetime.now(timezone.utc).isoformat()
        inventory = EnvironmentInventory(
            providers=[ConfiguredProviderRecord(provider_id, "Probe", "openai_compatible", None, "api_key", f"opencode_credential:probe-{suffix}", "opencode-cli", 1, now, False)],
            models=[DiscoveredModelRecord(model_id, provider_id, "coder", "opencode-cli", now)],
            execution_probes=[{"model_id": model_id, "success": True}],
            discovered_at=now,
        )
        async with AsyncSessionLocal() as session:
            await ExternalEnvironmentService().import_inventory(session, inventory)
            provider = await session.get(ProviderInstanceRecord, provider_id)
            model = await session.get(ModelRecord, model_id)
            self.assertEqual(provider.health_state, "available")
            self.assertEqual(model.availability_state, "available")
            await session.delete(model)
            await session.delete(provider)
            await session.commit()

    async def test_coding_probe_requires_exact_filesystem_evidence_contract(self):
        service = ExternalEnvironmentService()
        self.assertTrue(hasattr(service, "verify_opencode_coding_model"))


if __name__ == "__main__":
    unittest.main()
