import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelRecord
from core.ai_fleet.services.model_registry import ModelRegistryService


class ModelRegistryAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.service = ModelRegistryService()

    def test_cloud_catalog_is_not_executable_from_credentials_alone(self):
        model = ModelRecord(id="cloud", name="Cloud", provider="openai", registry_state="catalog", lifecycle_status="active", is_active=True)
        missing = self.service.assess(model, {}, {})
        configured = self.service.assess(model, {"openai": {"is_configured": True}}, {})
        self.assertEqual(missing["state"], "catalog")
        self.assertFalse(missing["executable"])
        self.assertEqual(configured["state"], "configured")
        self.assertFalse(configured["executable"])
        self.assertEqual(configured["code"], "availability_unverified")

    def test_local_model_requires_exact_runtime_report(self):
        model = ModelRecord(id="llama3.3", name="llama3.3", provider="ollama", is_local=True, lifecycle_status="active", is_active=True)
        absent = self.service.assess(model, {}, {"running": True, "models": [{"name": "other"}]})
        present = self.service.assess(model, {}, {"running": True, "models": [{"name": "llama3.3"}]})
        self.assertEqual(absent["state"], "discovered")
        self.assertFalse(absent["executable"])
        self.assertEqual(present["state"], "executable")
        self.assertTrue(present["executable"])

    def test_stale_cloud_observation_is_not_executable(self):
        from datetime import datetime, timedelta
        model = ModelRecord(id="stale", name="Stale", provider="openai", lifecycle_status="active", is_active=True, availability_state="available", availability_expires_at=datetime.utcnow() - timedelta(seconds=1))
        state = self.service.assess(model, {"openai": {"is_configured": True}}, {})
        self.assertEqual(state["code"], "availability_stale")
        self.assertFalse(state["executable"])

    def test_disabled_model_is_not_executable(self):
        model = ModelRecord(id="disabled", name="Disabled", provider="openai", lifecycle_status="active", is_active=False)
        state = self.service.assess(model, {"openai": {"is_configured": True}}, {})
        self.assertEqual(state["state"], "disabled")
        self.assertFalse(state["executable"])


class ModelLifecycleApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)
        self.ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(ModelRecord).where(ModelRecord.id.in_(self.ids)))
                await session.commit()

    async def test_create_update_stale_conflict_and_archive(self):
        payload = {"id": f"user-model-{id(self)}", "name": "User Model", "provider": "custom", "modalities": ["text", "code"], "source_type": "user"}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created_response = await client.post("/api/models", json=payload)
            self.assertEqual(created_response.status_code, 200)
            created = created_response.json()
            self.ids.append(created["id"])
            first = await client.patch(f"/api/models/{created['id']}", json={"expected_revision": created["revision"], "name": "Updated Model"})
            stale = await client.patch(f"/api/models/{created['id']}", json={"expected_revision": created["revision"], "name": "Stale"})
            archived = await client.delete(f"/api/models/{created['id']}")
        self.assertEqual(created["registry_state"], "catalog")
        self.assertEqual(created["availability_state"], "unknown")
        self.assertEqual(created["capability_provenance"], "unknown")
        self.assertIsNone(created["quality_score"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(archived.json()["lifecycle_status"], "archived")
        self.assertFalse(archived.json()["is_active"])

    async def test_availability_observation_has_expiry_and_changes_executable_assessment(self):
        model_id = f"observed-model-{id(self)}"
        self.ids.append(model_id)
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            await client.post("/api/models", json={"id": model_id, "name": "Observed", "provider": "openai"})
            observed = await client.post(f"/api/models/{model_id}/availability", json={"state": "available", "source": "provider", "evidence": {"operation": "list_models"}, "ttl_seconds": 60})
        self.assertEqual(observed.status_code, 200)
        payload = observed.json()
        self.assertEqual(payload["availability_state"], "available")
        self.assertIsNotNone(payload["availability_expires_at"])
        async with AsyncSessionLocal() as session:
            record = await session.get(ModelRecord, model_id)
            state = ModelRegistryService().assess(record, {"openai": {"is_configured": True}}, {})
        self.assertTrue(state["executable"])
        self.assertEqual(state["state"], "executable")

    async def test_invalid_id_modality_and_provenance_fields_are_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            invalid_id = await client.post("/api/models", json={"id": "Bad ID", "name": "Bad", "provider": "custom"})
            invalid_modality = await client.post("/api/models", json={"id": "bad-modality", "name": "Bad", "provider": "custom", "modalities": ["telepathy"]})
            forged = await client.post("/api/models", json={"id": "forged-model", "name": "Forged", "provider": "custom", "capability_provenance": "measured"})
        self.assertEqual(invalid_id.status_code, 422)
        self.assertEqual(invalid_modality.status_code, 422)
        self.assertEqual(forged.status_code, 422)


class ModelTruthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)

    async def test_catalog_models_expose_unknown_truth_not_seeded_scores(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        models = response.json()
        self.assertTrue(models)
        for model in models:
            self.assertEqual(model["registry_state"], "catalog")
            self.assertEqual(model["availability_state"], "unknown")
            self.assertEqual(model["metadata_provenance"], "unverified")
            self.assertEqual(model["capability_provenance"], "unknown")
            self.assertEqual(model["pricing_provenance"], "unknown")
            self.assertIsNone(model["input_cost_per_m"])
            self.assertIsNone(model["output_cost_per_m"])
            self.assertIsNone(model["quality_score"])
            self.assertIsNone(model["speed_score"])
            self.assertIsNone(model["reliability_score"])

    async def test_preflight_does_not_execute_configured_but_unobserved_cloud_model(self):
        from unittest.mock import patch

        configured_scan = {
            "configured_providers": {"openai": {"is_configured": True}},
            "discovered_tools": [],
            "ollama_status": {"running": False, "models": []},
        }
        with patch("core.ai_fleet.engine.execution_readiness.system_scanner.scan_system", return_value=configured_scan):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.post("/api/tasks/preflight", json={"prompt": "hello", "model_id": "gpt-4o"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_execute"])
        self.assertEqual(payload["recommended_model_state"]["state"], "configured")
        self.assertFalse(payload["recommended_model_state"]["executable"])

    async def test_active_catalog_flag_does_not_imply_availability(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            models = (await client.get("/api/models")).json()
        active = [model for model in models if model["is_active"]]
        self.assertTrue(active)
        self.assertTrue(all(model["availability_state"] == "unknown" for model in active))


if __name__ == "__main__":
    unittest.main()
