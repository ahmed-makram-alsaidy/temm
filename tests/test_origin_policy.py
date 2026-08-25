import unittest

from fastapi.testclient import TestClient

from core.ai_fleet.main import app, is_local_origin


class OriginPolicyTests(unittest.TestCase):
    def test_local_origin_predicate(self):
        self.assertTrue(is_local_origin(None))
        self.assertTrue(is_local_origin("http://localhost:5173"))
        self.assertTrue(is_local_origin("https://127.0.0.1:8787"))
        self.assertFalse(is_local_origin("null"))
        self.assertFalse(is_local_origin("https://evil.example"))
        self.assertFalse(is_local_origin("file://localhost/test"))

    def test_cors_allows_local_and_rejects_foreign_origin(self):
        with TestClient(app) as client:
            local = client.options(
                "/api/agents",
                headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
            )
            foreign = client.options(
                "/api/agents",
                headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
            )
        self.assertEqual(local.status_code, 200)
        self.assertEqual(local.headers.get("access-control-allow-origin"), "http://localhost:5173")
        self.assertEqual(foreign.status_code, 400)
        self.assertIsNone(foreign.headers.get("access-control-allow-origin"))

    def test_foreign_browser_request_is_rejected_before_route(self):
        with TestClient(app) as client:
            response = client.post("/api/scanner/detect", headers={"origin": "https://evil.example"})
            cross_site = client.post("/api/scanner/detect", headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "foreign_origin")
        self.assertEqual(cross_site.status_code, 403)

    def test_originless_native_client_remains_supported(self):
        with TestClient(app) as client:
            response = client.get("/api/terminal/capabilities")
        self.assertEqual(response.status_code, 200)

    def test_invalid_host_is_rejected(self):
        with TestClient(app) as client:
            response = client.get("/api/terminal/capabilities", headers={"host": "evil.example"})
        self.assertEqual(response.status_code, 400)

    def test_terminal_websocket_rejects_foreign_origin(self):
        with TestClient(app) as client:
            with self.assertRaises(Exception):
                with client.websocket_connect("/ws/terminal/origin-test", headers={"origin": "https://evil.example"}):
                    pass


if __name__ == "__main__":
    unittest.main()
