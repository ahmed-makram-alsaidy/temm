import unittest

import httpx
from sqlalchemy import delete

from aifleet_sdk import AiFleetClient, AiFleetSdkError, AiFleetValidationError, Project
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, ProjectRecord


class SdkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.id = None
        self.client = AiFleetClient("http://test", httpx.ASGITransport(app=app))

    async def asyncTearDown(self):
        await self.client.close()
        if self.id:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.id))
                await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.id))
                await session.commit()

    async def test_version_negotiation_and_typed_projects(self):
        contract = await self.client.negotiate()
        self.assertEqual(contract["domain_schema_version"], "1.0")
        project = await self.client.create_project("SDK", f"sdk-{id(self)}", "software", "Publish a verified changelog page")
        self.id = project.id
        self.assertIsInstance(project, Project)
        projects = await self.client.list_projects()
        self.assertIn(project.id, [item.id for item in projects])

    async def test_a_project_without_explicit_intent_is_refused_before_any_request(self):
        """A project records what someone wants accomplished, so the SDK may not send
        blank intent - and may not invent intent to fill the gap either."""
        sent = []
        original = self.client.client.request

        async def watch(method, path, **kwargs):
            sent.append((method, path))
            return await original(method, path, **kwargs)

        self.client.client.request = watch
        try:
            for absent in ["", "   ", None]:
                with self.assertRaises(AiFleetValidationError) as refused:
                    await self.client.create_project("SDK", f"sdk-empty-{id(self)}", "software", absent)
                self.assertEqual(refused.exception.code, "goal_required")
                self.assertIn("goal", str(refused.exception))
            # Local misuse stays catchable as ValueError, which is this client's existing
            # contract for a call it refuses itself.
            with self.assertRaises(ValueError):
                await self.client.create_project("SDK", f"sdk-empty-{id(self)}", "software")
        finally:
            self.client.client.request = original
        self.assertEqual(sent, [], "A refused call must not reach the server.")

    async def test_the_earlier_purpose_keyword_still_carries_the_goal(self):
        project = await self.client.create_project("SDK", f"sdk-alias-{id(self)}", "software", purpose="Ship a verified pricing table")
        self.id = project.id
        self.assertIsInstance(project, Project)

    async def test_the_backend_itself_still_refuses_blank_intent(self):
        """The client-side rule is a better error, not the only enforcement."""
        with self.assertRaises(AiFleetSdkError) as refused:
            await self.client.request("POST", "/api/projects", json={"name": "SDK", "slug": f"sdk-raw-{id(self)}", "project_type": "software", "purpose": "", "owner": "local_owner"})
        self.assertEqual(refused.exception.status_code, 422)
        self.assertEqual(refused.exception.code, "validation_failed")

    async def test_incompatible_version_and_errors_are_typed(self):
        with self.assertRaises(AiFleetSdkError) as context:
            await self.client.negotiate(2)
        self.assertEqual(context.exception.code, "incompatible_schema")
        with self.assertRaises(AiFleetSdkError) as missing:
            await self.client.get_run("missing")
        self.assertEqual(missing.exception.status_code, 404)

    async def test_public_request_is_api_scoped_and_connection_errors_are_typed(self):
        with self.assertRaises(ValueError):
            await self.client.request("GET", "/health/live")
        client = AiFleetClient("http://127.0.0.1:1", timeout_seconds=.1)
        try:
            with self.assertRaises(AiFleetSdkError) as failure:
                await client.negotiate()
            self.assertIn(failure.exception.code, {"connection_failed", "request_timeout"})
        finally:
            await client.close()

    async def test_async_context_manager_closes_client(self):
        async with AiFleetClient("http://test", httpx.ASGITransport(app=app)) as client:
            await client.negotiate()
        self.assertTrue(client.client.is_closed)


if __name__ == "__main__":
    unittest.main()
