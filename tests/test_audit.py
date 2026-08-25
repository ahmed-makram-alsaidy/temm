import unittest

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.audit import AuditService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord
from core.ai_fleet.storage.secret_vault import secret_vault


class AuditServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.prefix = f"audit-test-{id(self)}"

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id.like(f"{self.prefix}%")))
            await session.commit()

    async def test_append_query_cursor_and_redaction(self):
        secret = "audit-secret-82039475"
        secret_vault.set_key("audit-test", secret)
        try:
            async with AsyncSessionLocal() as session:
                service = AuditService()
                one = await service.append(session, action="test.one", resource_type="test", resource_id=f"{self.prefix}-one", details={"value": secret})
                two = await service.append(session, action="test.two", resource_type="test", resource_id=f"{self.prefix}-two", details={"safe": True})
                await session.commit()
                rows = await service.query(session, after_sequence=one.sequence, resource_type="test")
            self.assertTrue(any(row.audit_id == two.audit_id for row in rows))
            self.assertNotIn(secret, one.details)
            self.assertIn("[REDACTED]", one.details)
        finally:
            secret_vault.delete_key("audit-test")


class AuditApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)

    async def test_audit_api_is_read_only_and_paginated(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            settings = await client.patch("/api/settings", json={"settings": {"monthly_ai_budget": 123.0}})
            response = await client.get("/api/audit?action=settings.updated&limit=10")
            mutation = await client.post("/api/audit", json={})
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json())
        self.assertTrue(all(item["action"] == "settings.updated" for item in response.json()))
        self.assertIn("x-next-cursor", response.headers)
        self.assertEqual(mutation.status_code, 405)


if __name__ == "__main__":
    unittest.main()
