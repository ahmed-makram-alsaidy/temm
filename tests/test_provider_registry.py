import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelRecord, ProviderInstanceRecord
from core.ai_fleet.storage.secret_vault import secret_vault


class ProviderRegistryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)
        self.ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(ModelRecord).where(ModelRecord.source_uri.in_([f"provider:{item}" for item in self.ids])))
                await session.execute(delete(ProviderInstanceRecord).where(ProviderInstanceRecord.id.in_(self.ids)))
                await session.commit()

    async def create(self, client, instance_id):
        response = await client.post("/api/providers", json={
            "id": instance_id,
            "name": instance_id,
            "adapter_id": "openai-compatible",
            "capabilities": ["configure", "auth", "health", "list_models", "execute", "stream", "cancel"],
            "configuration": {"base_url": "https://example.invalid/v1", "organization": "test"},
        })
        if response.status_code == 200:
            self.ids.append(instance_id)
        return response

    async def test_multiple_instances_stable_ids_and_unknown_health(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            one = await self.create(client, f"provider-one-{id(self)}")
            two = await self.create(client, f"provider-two-{id(self)}")
        self.assertEqual(one.status_code, 200)
        self.assertEqual(two.status_code, 200)
        self.assertEqual(one.json()["adapter_id"], two.json()["adapter_id"])
        self.assertEqual(one.json()["health_state"], "unknown")
        self.assertEqual(one.json()["lifecycle_status"], "active")
        self.assertNotIn("api_key", one.json()["configuration"])

    async def test_sensitive_configuration_and_invalid_capabilities_are_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            sensitive = await client.post("/api/providers", json={"id": f"sensitive-{id(self)}", "name": "Sensitive", "adapter_id": "x", "configuration": {"api_key": "secret"}})
            invalid = await client.post("/api/providers", json={"id": f"invalid-{id(self)}", "name": "Invalid", "adapter_id": "x", "capabilities": ["telepathy"]})
            stream_only = await client.post("/api/providers", json={"id": f"stream-{id(self)}", "name": "Stream", "adapter_id": "x", "capabilities": ["stream"]})
        self.assertEqual(sensitive.status_code, 422)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(stream_only.status_code, 422)

    async def test_health_observation_is_current_then_stale_and_redacted(self):
        from datetime import datetime, timedelta
        instance_id = f"provider-health-{id(self)}"
        secret = "provider-health-secret-729304"
        secret_vault.set_key("provider-health-test", secret)
        try:
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                await self.create(client, instance_id)
                observed = await client.post(f"/api/providers/{instance_id}/health", json={"state": "healthy", "evidence": {"authorization": secret}, "ttl_seconds": 60})
                current = await client.get(f"/api/providers/{instance_id}/health")
            self.assertEqual(observed.status_code, 200)
            self.assertEqual(current.json()["state"], "healthy")
            self.assertTrue(current.json()["usable"])
            self.assertNotIn(secret, observed.text)
            async with AsyncSessionLocal() as session:
                record = await session.get(ProviderInstanceRecord, instance_id)
                record.health_expires_at = datetime.utcnow() - timedelta(seconds=1)
                await session.commit()
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                stale = await client.get(f"/api/providers/{instance_id}/health")
            self.assertEqual(stale.json()["state"], "unknown")
            self.assertFalse(stale.json()["usable"])
        finally:
            secret_vault.delete_key("provider-health-test")

    async def test_model_ingestion_is_namespaced_truthful_and_marks_missing_unavailable(self):
        instance_id = f"provider-models-{id(self)}"
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            await self.create(client, instance_id)
            first = await client.post(f"/api/providers/{instance_id}/models/ingest", json={"models": [
                {"model_id": "alpha", "display_name": "Alpha", "modalities": ["text"]},
                {"model_id": "beta", "display_name": "Beta", "modalities": ["text", "vision"]},
            ], "ttl_seconds": 60})
            second = await client.post(f"/api/providers/{instance_id}/models/ingest", json={"models": [
                {"model_id": "alpha", "display_name": "Alpha", "modalities": ["text"]},
            ], "ttl_seconds": 60})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.json()), 2)
        alpha = first.json()[0]
        self.assertTrue(alpha["id"].startswith(f"{instance_id}:"))
        self.assertEqual(alpha["availability_state"], "available")
        self.assertEqual(alpha["metadata_provenance"], "provider_reported")
        self.assertEqual(alpha["pricing_provenance"], "unknown")
        self.assertIsNone(alpha["quality_score"])
        self.assertEqual(second.status_code, 200)
        async with AsyncSessionLocal() as session:
            beta = await session.get(ModelRecord, f"{instance_id}:beta")
            self.assertEqual(beta.availability_state, "unavailable")
            self.assertEqual(beta.lifecycle_status, "active")

    async def test_local_runtime_ingestion_does_not_infer_price_or_capability(self):
        instance_id = f"local-runtime-{id(self)}"
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/providers", json={"id": instance_id, "name": "Local Runtime", "adapter_id": "local-runtime", "capabilities": ["health", "list_models", "execute", "stream", "cancel"], "configuration": {"runtime": "local"}})
            if created.status_code == 200:
                self.ids.append(instance_id)
            ingested = await client.post(f"/api/providers/{instance_id}/models/ingest", json={"models": [{"model_id": "local-one", "display_name": "Local One", "modalities": ["text"]}]})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(ingested.status_code, 200)
        model = ingested.json()[0]
        self.assertEqual(model["pricing_provenance"], "unknown")
        self.assertEqual(model["capability_provenance"], "unknown")
        self.assertIsNone(model["quality_score"])
        self.assertIsNone(model["input_cost_per_m"])

    async def test_revision_secret_redaction_and_archive_cleanup(self):
        instance_id = f"provider-lifecycle-{id(self)}"
        secret = "provider-secret-value-9203847"
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await self.create(client, instance_id)
            payload = created.json()
            updated = await client.patch(f"/api/providers/{instance_id}", json={"expected_revision": payload["revision"], "name": "Updated"})
            stale = await client.patch(f"/api/providers/{instance_id}", json={"expected_revision": payload["revision"], "name": "Stale"})
            saved = await client.put(f"/api/providers/{instance_id}/secrets", json={"reference": "API_KEY", "value": secret})
            listed = await client.get(f"/api/providers/{instance_id}/secrets")
            providers = await client.get("/api/providers")
            archived = await client.delete(f"/api/providers/{instance_id}")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(listed.json(), [{"reference": "API_KEY", "configured": True}])
        self.assertNotIn(secret, saved.text + listed.text + providers.text + archived.text)
        self.assertTrue(archived.json()["archived"])
        self.assertFalse(secret_vault.has_key(f"provider:{instance_id}:api_key"))
        async with AsyncSessionLocal() as session:
            record = await session.get(ProviderInstanceRecord, instance_id)
            self.assertEqual(record.lifecycle_status, "archived")
            self.assertFalse(record.user_enabled)
            self.assertEqual(record.health_state, "unknown")


if __name__ == "__main__":
    unittest.main()
