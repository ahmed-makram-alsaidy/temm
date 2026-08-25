import json
import unittest

import httpx

from core.ai_fleet.errors import DomainError
from core.ai_fleet.openai_compatible import OpenAICompatibleAdapter


class FakeVault:
    def __init__(self, value=None):
        self.value = value

    def get_key(self, key):
        return self.value


class OpenAICompatibleAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_policy(self):
        self.assertEqual(OpenAICompatibleAdapter.validate_base_url("https://api.example/v1"), "https://api.example/v1")
        self.assertEqual(OpenAICompatibleAdapter.validate_base_url("http://127.0.0.1:8000/v1", True), "http://127.0.0.1:8000/v1")
        for url in ["http://api.example/v1", "file:///tmp", "http://169.254.169.254"]:
            with self.assertRaises(DomainError):
                OpenAICompatibleAdapter.validate_base_url(url)

    async def test_stream_mapping_usage_and_auth(self):
        captured = {}

        async def handler(request):
            captured["authorization"] = request.headers.get("authorization")
            captured["json"] = json.loads(request.content)
            body = 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: {"choices":[],"usage":{"completion_tokens":7}}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        adapter = OpenAICompatibleAdapter("custom", "https://api.example/v1", FakeVault("secret-value"), "CUSTOM_KEY", {"catalog": "real-model"}, transport=httpx.MockTransport(handler))
        events = [event async for event in adapter.stream("catalog", "prompt", "request")]
        self.assertEqual(captured["authorization"], "Bearer secret-value")
        self.assertEqual(captured["json"]["model"], "real-model")
        self.assertEqual(events[0].text, "Hello")
        self.assertEqual(events[-1].usage.output_tokens, 7)
        self.assertEqual(events[-1].usage.source, "provider_reported")

    async def test_http_errors_are_sanitized(self):
        async def handler(request):
            return httpx.Response(401, text="secret upstream body")

        adapter = OpenAICompatibleAdapter("custom", "https://api.example/v1", FakeVault("secret-value"), "CUSTOM_KEY", transport=httpx.MockTransport(handler))
        events = [event async for event in adapter.stream("model", "prompt", "request")]
        self.assertEqual(events[0].event_type, "error")
        self.assertEqual(events[0].error_code, "provider_http_401")
        self.assertNotIn("secret upstream", events[0].text)

    async def test_missing_secret_returns_configuration_error(self):
        adapter = OpenAICompatibleAdapter("custom", "https://api.example/v1", FakeVault(), "CUSTOM_KEY", transport=httpx.MockTransport(lambda request: httpx.Response(500)))
        events = [event async for event in adapter.stream("model", "prompt", "request")]
        self.assertEqual(events[0].error_code, "execution_not_configured")


if __name__ == "__main__":
    unittest.main()
