import asyncio
from abc import abstractmethod
from typing import AsyncIterator, Dict

from ..engine.real_llm_client import RealLLMClient, real_llm_client
from ..providers import ProviderAdapter, ProviderCapability, ProviderStreamEvent, ProviderUsageObservation
from ..storage.secret_vault import SecretVault, secret_vault


class CancellableStreamingAdapter(ProviderAdapter):
    capabilities = frozenset({ProviderCapability.EXECUTE, ProviderCapability.STREAM, ProviderCapability.CANCEL})

    def __init__(self, adapter_id: str):
        self.adapter_id = adapter_id
        self._active: Dict[str, tuple[asyncio.Task, asyncio.Event]] = {}

    @abstractmethod
    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        if False:
            yield {}

    async def stream(self, model_id: str, prompt: str, request_id: str) -> AsyncIterator[ProviderStreamEvent]:
        self.require(ProviderCapability.STREAM)
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        cancelled = asyncio.Event()

        async def produce():
            try:
                async with asyncio.timeout(120):
                    async for item in self.source_stream(model_id, prompt):
                        if cancelled.is_set():
                            break
                        await queue.put(item)
            except asyncio.CancelledError:
                cancelled.set()
            except asyncio.TimeoutError:
                await queue.put({"type": "error", "code": "execution_timeout", "text": "Provider execution timed out."})
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        self._active[request_id] = (producer, cancelled)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                item_type = item.get("type")
                if item_type == "chunk":
                    yield ProviderStreamEvent("chunk", text=item.get("text", ""))
                elif item_type == "done":
                    usage = ProviderUsageObservation(
                        checked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                        output_tokens=item.get("tokens"),
                        source="provider_reported" if item.get("usage_source") == "provider" else "estimated",
                    )
                    yield ProviderStreamEvent("done", usage=usage)
                elif item_type == "error":
                    yield ProviderStreamEvent("error", text=item.get("text", "Provider execution failed."), error_code=item.get("code", "provider_error"))
            if cancelled.is_set():
                yield ProviderStreamEvent("cancelled", error_code="execution_cancelled")
        finally:
            self._active.pop(request_id, None)
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def cancel(self, request_id: str) -> bool:
        active = self._active.get(request_id)
        if not active:
            return False
        task, event = active
        event.set()
        task.cancel()
        return True


class OpenAICompatibleBuiltinAdapter(CancellableStreamingAdapter):
    def __init__(self, provider_id: str, base_url: str, client: RealLLMClient, vault: SecretVault, model_resolver=None):
        super().__init__(f"builtin-{provider_id}")
        self.provider_id = provider_id
        self.base_url = base_url
        self.client = client
        self.vault = vault
        self.model_resolver = model_resolver or (lambda model_id: model_id)

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        key = self.vault.get_key(self.provider_id)
        if not key:
            yield {"type": "error", "code": "execution_not_configured", "text": "Provider credentials are not configured."}
            return
        async for item in self.client._stream_openai_compatible(self.base_url, key, self.model_resolver(model_id), prompt):
            yield item


class GeminiBuiltinAdapter(CancellableStreamingAdapter):
    def __init__(self, client: RealLLMClient, vault: SecretVault):
        super().__init__("builtin-google")
        self.client = client
        self.vault = vault

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        key = self.vault.get_key("google")
        if not key:
            yield {"type": "error", "code": "execution_not_configured", "text": "Provider credentials are not configured."}
            return
        async for item in self.client._stream_gemini(model_id, prompt, key):
            yield item


class AnthropicBuiltinAdapter(CancellableStreamingAdapter):
    def __init__(self, client: RealLLMClient, vault: SecretVault):
        super().__init__("builtin-anthropic")
        self.client = client
        self.vault = vault

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        key = self.vault.get_key("anthropic")
        if not key:
            yield {"type": "error", "code": "execution_not_configured", "text": "Provider credentials are not configured."}
            return
        async for item in self.client._stream_anthropic(model_id, prompt, key):
            yield item


class OllamaBuiltinAdapter(CancellableStreamingAdapter):
    def __init__(self, client: RealLLMClient):
        super().__init__("builtin-ollama")
        self.client = client

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        async for item in self.client._stream_ollama(model_id, prompt):
            yield item


class BedrockBuiltinAdapter(CancellableStreamingAdapter):
    """AWS Bedrock Converse API adapter using Bearer token authentication."""

    BEDROCK_ENDPOINT = "https://bedrock-runtime.us-east-1.amazonaws.com"
    DEFAULT_MODEL = "amazon.nova-micro-v1:0"

    def __init__(self, vault: SecretVault):
        super().__init__("builtin-bedrock")
        self.vault = vault

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        import httpx

        token = self.vault.get_key("bedrock")
        if not token:
            yield {"type": "error", "code": "execution_not_configured", "text": "AWS Bedrock credentials are not configured."}
            return
        resolved_model = model_id if model_id and ":" in model_id else self.DEFAULT_MODEL
        url = f"{self.BEDROCK_ENDPOINT}/model/{resolved_model}/converse"
        body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 4096},
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, headers=headers, json=body)
                if response.status_code != 200:
                    yield {"type": "error", "code": f"provider_http_{response.status_code}", "text": f"Bedrock request failed: {response.text[:200]}"}
                    return
                data = response.json()
                output = data.get("output", {}).get("message", {}).get("content", [])
                text = output[0].get("text", "") if output else ""
                if text:
                    yield {"type": "chunk", "text": text}
                usage = data.get("usage", {})
                total_tokens = usage.get("outputTokens")
                yield {"type": "done", "tokens": total_tokens, "usage_source": "provider" if total_tokens is not None else "unknown"}
        except httpx.TimeoutException:
            yield {"type": "error", "code": "execution_timeout", "text": "Bedrock request timed out."}
        except Exception as exc:
            yield {"type": "error", "code": "provider_error", "text": f"Bedrock execution error: {exc}"}


class UnsupportedBuiltinAdapter(CancellableStreamingAdapter):
    def __init__(self, provider_id: str):
        super().__init__(f"builtin-unsupported-{provider_id}")
        self.provider_id = provider_id

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        yield {"type": "error", "code": "provider_adapter_missing", "text": "No built-in execution adapter is available for this provider."}


class ProviderRuntimeRegistry:
    def __init__(self, client: RealLLMClient, vault: SecretVault = secret_vault):
        self._client = client
        self._vault = vault
        self._adapters: Dict[str, CancellableStreamingAdapter] = {
            "openai": OpenAICompatibleBuiltinAdapter("openai", "https://api.openai.com/v1", client, vault, lambda model_id: "gpt-4o" if "4o" in model_id else "gpt-4o-mini"),
            "groq": OpenAICompatibleBuiltinAdapter("groq", "https://api.groq.com/openai/v1", client, vault, lambda model_id: "llama-3.3-70b-versatile" if "70b" in model_id else "llama-3.1-8b-instant"),
            "deepseek": OpenAICompatibleBuiltinAdapter("deepseek", "https://api.deepseek.com", client, vault, lambda model_id: "deepseek-reasoner" if "r1" in model_id.lower() else "deepseek-chat"),
            "google": GeminiBuiltinAdapter(client, vault),
            "gemini": GeminiBuiltinAdapter(client, vault),
            "anthropic": AnthropicBuiltinAdapter(client, vault),
            "claude": AnthropicBuiltinAdapter(client, vault),
            "ollama": OllamaBuiltinAdapter(client),
            "bedrock": BedrockBuiltinAdapter(vault),
        }

    def resolve(self, provider_id: str) -> CancellableStreamingAdapter:
        canonical = provider_id.lower()
        return self._adapters.get(canonical) or UnsupportedBuiltinAdapter(canonical)

    async def cancel(self, request_id: str) -> bool:
        unique = {id(adapter): adapter for adapter in self._adapters.values()}.values()
        results = await asyncio.gather(*(adapter.cancel(request_id) for adapter in unique))
        return any(results)


provider_runtime_registry = ProviderRuntimeRegistry(real_llm_client)
