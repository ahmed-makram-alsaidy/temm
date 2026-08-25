import json
import unittest
import uuid
from datetime import datetime

from core.ai_fleet.errors import DomainError
from core.ai_fleet.services.community_leaderboards import CommunityLeaderboardService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import BenchmarkSuiteVersionRecord, ModelRecord, SystemSetting, TaskRun


class CommunityLeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:10]
        self.suite_id = f"suite-community-{suffix}"
        self.model_id = f"model-community-{suffix}"
        self.run_id = f"run-community-{suffix}"
        self.service = CommunityLeaderboardService()
        async with AsyncSessionLocal() as session:
            session.add(BenchmarkSuiteVersionRecord(id=self.suite_id, suite_key=f"community-{suffix}", version=1, name="Community", category="coding", provenance="user_authored", source_uri="local", content_hash="e" * 64))
            session.add(ModelRecord(id=self.model_id, name="Private Model Name", provider="private-provider", source_type="user", registry_state="configured", lifecycle_status="active"))
            session.add(TaskRun(id=self.run_id, prompt="private prompt", status="completed", selected_model_id=self.model_id, quality_eval_score=92.7, quality_provenance="measured", completed_at=datetime(2026, 8, 16, 12, 34, 56), measurement_metadata=json.dumps({"benchmark": {"suite_version_id": self.suite_id, "content_hash": "e" * 64}})))
            setting = await session.get(SystemSetting, "community_leaderboard_consent")
            if setting:
                setting.value = "false"
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            for model, key in ((TaskRun, self.run_id), (ModelRecord, self.model_id), (BenchmarkSuiteVersionRecord, self.suite_id)):
                record = await session.get(model, key)
                if record:
                    await session.delete(record)
            setting = await session.get(SystemSetting, "community_leaderboard_consent")
            if setting:
                setting.value = "false"
            await session.commit()

    async def test_preview_excludes_identifiers_and_does_not_upload(self):
        async with AsyncSessionLocal() as session:
            preview = await self.service.preview(session, self.suite_id)
        encoded = json.dumps(preview)
        for secret in (self.model_id, "Private Model Name", "private-provider", "private prompt", self.run_id):
            self.assertNotIn(secret, encoded)
        self.assertFalse(preview["upload_performed"])
        self.assertEqual(preview["rows"][0]["score_band"], 95)
        self.assertEqual(preview["rows"][0]["observation_month"], "2026-08")
        self.assertIn("model_id", preview["excluded_fields"])

    async def test_export_requires_consent_and_revocation_blocks_future_exports(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(DomainError):
                await self.service.export(session, self.suite_id)
            enabled = await self.service.consent(session, True)
            self.assertTrue(enabled["enabled"])
            exported = await self.service.export(session, self.suite_id)
            self.assertTrue(exported["export_id"].startswith("community-export-"))
            self.assertFalse(exported["upload_performed"])
            revoked = await self.service.consent(session, False)
            self.assertFalse(revoked["enabled"])
            self.assertFalse(revoked["remote_revocation_claimed"])
            with self.assertRaises(DomainError):
                await self.service.export(session, self.suite_id)


if __name__ == "__main__":
    unittest.main()
