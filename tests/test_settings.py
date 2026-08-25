import unittest

import httpx

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import SystemSetting


class SettingsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)

    async def test_settings_read_is_typed_and_versioned(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertIsInstance(payload["settings"]["monthly_ai_budget"], float)
        self.assertIsInstance(payload["settings"]["economy_auto_switch"], bool)

    async def test_valid_settings_update_round_trips_types(self):
        changes = {
            "monthly_ai_budget": 250.5,
            "budget_alert_threshold": 75,
            "default_routing_strategy": "economy",
            "hourly_productivity_value": 40,
            "economy_auto_switch": False,
        }
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.patch("/api/settings", json={"settings": changes})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"], {**changes, "budget_alert_threshold": 75.0, "hourly_productivity_value": 40.0, "telemetry_retention_days": 365, "community_leaderboard_consent": False})

    async def test_invalid_and_unknown_settings_are_rejected(self):
        cases = [
            {"monthly_ai_budget": -1},
            {"budget_alert_threshold": 101},
            {"default_routing_strategy": "random"},
            {"economy_auto_switch": "yes"},
            {"unknown_setting": True},
        ]
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            for changes in cases:
                response = await client.patch("/api/settings", json={"settings": changes})
                self.assertEqual(response.status_code, 422, changes)
                self.assertEqual(response.json()["detail"]["code"], "validation_failed")

    async def test_malformed_stored_value_falls_back_without_crashing(self):
        async with AsyncSessionLocal() as session:
            record = await session.get(SystemSetting, "monthly_ai_budget")
            record.value = "not-a-number"
            await session.commit()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["monthly_ai_budget"], 100.0)


if __name__ == "__main__":
    unittest.main()
