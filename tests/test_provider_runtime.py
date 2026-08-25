import asyncio
import unittest

from core.ai_fleet.services.provider_runtime import CancellableStreamingAdapter, OpenAICompatibleBuiltinAdapter, ProviderRuntimeRegistry


class FakeVault:
    def __init__(self, values=None):
        self.values = values or {}

    def get_key(self, key):
        return self.values.get(key)


class FakeClient:
    def __init__(self, wait=False):
        self.wait = wait
        self.calls = []

    async def _stream_openai_compatible(self, base_url, api_key, model, prompt, system_instruction=None):
        self.calls.append((base_url, api_key, model, prompt))
        yield {"type": "chunk", "text": "hello"}
        if self.wait:
            await asyncio.sleep(30)
        yield {"type": "done", "tokens": 3, "usage_source": "provider"}

    async def _stream_gemini(self, model_id, prompt, api_key, system_instruction=None):
        yield {"type": "done", "tokens": 1}

    async def _stream_anthropic(self, model_id, prompt, api_key, system_instruction=None):
        yield {"type": "done", "tokens": 1}

    async def _stream_ollama(self, model_id, prompt, system_instruction=None):
        yield {"type": "done", "tokens": 1}


class TestAdapter(CancellableStreamingAdapter):
    def __init__(self, client):
        super().__init__("test")
        self.client = client

    async def source_stream(self, model_id, prompt):
        async for item in self.client._stream_openai_compatible("https://test", "key", model_id, prompt):
            yield item


class ProviderRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_is_normalized_and_cleans_active_request(self):
        adapter = TestAdapter(FakeClient())
        events = [event async for event in adapter.stream("model", "prompt", "request-1")]
        self.assertEqual([event.event_type for event in events], ["chunk", "done"])
        self.assertEqual(events[0].text, "hello")
        self.assertEqual(events[1].usage.output_tokens, 3)
        self.assertEqual(events[1].usage.source, "provider_reported")
        self.assertNotIn("request-1", adapter._active)

    async def test_cancel_stops_active_stream(self):
        adapter = TestAdapter(FakeClient(wait=True))
        events = []

        async def consume():
            async for event in adapter.stream("model", "prompt", "request-cancel"):
                events.append(event)

        task = asyncio.create_task(consume())
        for _ in range(100):
            if "request-cancel" in adapter._active:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(await adapter.cancel("request-cancel"))
        await asyncio.wait_for(task, timeout=2)
        self.assertTrue(any(event.event_type == "cancelled" for event in events))
        self.assertFalse(await adapter.cancel("request-cancel"))

    async def test_builtin_openai_adapter_preserves_mapping(self):
        client = FakeClient()
        adapter = OpenAICompatibleBuiltinAdapter("openai", "https://api.example/v1", client, FakeVault({"openai": "secret"}), lambda model: "mapped-model")
        events = [event async for event in adapter.stream("catalog-model", "prompt", "mapped-request")]
        self.assertEqual(client.calls, [("https://api.example/v1", "secret", "mapped-model", "prompt")])
        self.assertEqual(events[-1].event_type, "done")

    async def test_missing_credentials_returns_normalized_error(self):
        adapter = OpenAICompatibleBuiltinAdapter("openai", "https://api.example/v1", FakeClient(), FakeVault())
        events = [event async for event in adapter.stream("model", "prompt", "missing-key")]
        self.assertEqual(events[0].event_type, "error")
        self.assertEqual(events[0].error_code, "execution_not_configured")

    async def test_registry_resolves_concrete_provider_families(self):
        registry = ProviderRuntimeRegistry(FakeClient(), FakeVault())
        self.assertEqual(registry.resolve("openai").adapter_id, "builtin-openai")
        self.assertEqual(registry.resolve("google").adapter_id, "builtin-google")
        self.assertEqual(registry.resolve("anthropic").adapter_id, "builtin-anthropic")
        self.assertEqual(registry.resolve("ollama").adapter_id, "builtin-ollama")
        self.assertTrue(registry.resolve("unknown").adapter_id.startswith("builtin-unsupported"))


if __name__ == "__main__":
    unittest.main()
