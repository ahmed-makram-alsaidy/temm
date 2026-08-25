import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ModelFavoriteRecord, ModelRecord


class ModelFavoriteApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.model_id = f"favorite-model-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=self.model_id, name="Favorite", provider="custom", source_type="user"))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.model_id))
            await session.execute(delete(ModelFavoriteRecord).where(ModelFavoriteRecord.model_id == self.model_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == self.model_id))
            await session.commit()

    async def test_favorite_is_preference_not_ranking_evidence(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.put(f"/api/models/{self.model_id}/favorites", json={"use_case": "Code Review"})
            duplicate = await client.put(f"/api/models/{self.model_id}/favorites", json={"use_case": "Code Review"})
            listing = await client.get("/api/models/favorites", params={"use_case": "code_review"})
            removed = await client.delete(f"/api/models/{self.model_id}/favorites/code_review")
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["provenance"], "user_preference")
        self.assertFalse(created.json()["ranking_evidence"])
        self.assertEqual(duplicate.json()["id"], created.json()["id"])
        self.assertEqual(len(listing.json()), 1)
        self.assertTrue(removed.json()["removed"])

    async def test_invalid_use_case_is_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.put(f"/api/models/{self.model_id}/favorites", json={"use_case": "!"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
