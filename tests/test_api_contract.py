import unittest

import httpx

from core.ai_fleet.main import app
from core.ai_fleet.storage.database import init_db
from core.ai_fleet.storage.secret_vault import secret_vault


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.transport = httpx.ASGITransport(app=app)

    async def test_success_responses_include_request_metadata_headers(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/fleet/health/live", headers={"X-Request-ID": "caller-request-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "caller-request-123")
        self.assertEqual(response.headers["x-api-schema-version"], "1.0")
        self.assertIn("T", response.headers["x-response-timestamp"])

    async def test_invalid_request_id_is_replaced(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/fleet/health/live", headers={"X-Request-ID": "x" * 200})
        self.assertTrue(response.headers["x-request-id"].startswith("req-"))

    async def test_http_errors_have_legacy_detail_and_canonical_error(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/tasks/does-not-exist/execution")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertIn("detail", payload)
        self.assertEqual(payload["error"]["schema_version"], "1.0")
        self.assertEqual(payload["error"]["code"], "execution_not_found")
        self.assertEqual(payload["meta"]["request_id"], response.headers["x-request-id"])

    async def test_validation_errors_expose_safe_field_metadata(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.patch("/api/settings", json={})
        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertTrue(payload["error"]["details"]["fields"])
        self.assertNotIn("input", str(payload["error"]["details"]["fields"]))

    async def test_error_payload_redacts_known_secret(self):
        secret = "contract-secret-72930485"
        secret_vault.set_key("contract-secret", secret)
        try:
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.get(f"/api/tasks/{secret}/execution")
            self.assertNotIn(secret, response.text)
        finally:
            secret_vault.delete_key("contract-secret")

    async def test_list_pagination_headers_are_bounded(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/tasks/history?limit=2")
            invalid = await client.get("/api/tasks/history?limit=1000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-page-limit"], "2")
        self.assertIn(response.headers["x-has-more"], {"true", "false"})
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
