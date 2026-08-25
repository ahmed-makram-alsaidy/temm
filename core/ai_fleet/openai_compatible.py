import json
from typing import AsyncIterator, Dict, Optional
from urllib.parse import urlparse

import httpx

from .errors import DomainError
from .providers import ProviderCapability, ProviderStreamEvent, ProviderUsageObservation
from .services.provider_runtime import CancellableStreamingAdapter
from .storage.secret_vault import SecretVault


class OpenAICompatibleAdapter(CancellableStreamingAdapter):
    capabilities = frozenset({ProviderCapability.EXECUTE, ProviderCapability.STREAM, ProviderCapability.CANCEL})

    def __init__(
        self,
        adapter_id: str,
        base_url: str,
        vault: SecretVault,
        secret_key: str,
        model_map: Optional[Dict[str, str]] = None,
        allow_local_http: bool = False,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(adapter_id)
        self.base_url = self.validate_base_url(base_url, allow_local_http)
        self.vault = vault
        self.secret_key = secret_key
        self.model_map = model_map or {}
        self.transport = transport

    @staticmethod
    def validate_base_url(value: str, allow_local_http: bool = False) -> str:
        parsed = urlparse(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme == "https" and parsed.hostname:
            return value.rstrip("/")
        if allow_local_http and parsed.scheme == "http" and local:
            return value.rstrip("/")
        raise DomainError("validation_failed", message="Provider base URL must use HTTPS; explicit local HTTP is limited to loopback hosts.")

    async def source_stream(self, model_id: str, prompt: str) -> AsyncIterator[dict]:
        api_key = self.vault.get_key(self.secret_key)
        if not api_key:
            yield {"type": "error", "code": "execution_not_configured", "text": "Provider credentials are not configured."}
            return
        model = self.model_map.get(model_id, model_id)
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        total_tokens = None
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, transport=self.transport) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        yield {"type": "error", "code": f"provider_http_{response.status_code}", "text": f"Provider request failed with HTTP {response.status_code}."}
                        return
                    async for line in response.aiter_lines():
                        if len(line) > 262144:
                            yield {"type": "error", "code": "provider_frame_too_large", "text": "Provider stream frame exceeded 256 KiB."}
                            return
                        if not line.startswith("data: "):
                            continue
                        content = line[6:]
                        if content == "[DONE]":
                            break
                        try:
                            item = json.loads(content)
                        except json.JSONDecodeError:
                            continue
                        usage = item.get("usage") or {}
                        if usage.get("completion_tokens") is not None:
                            total_tokens = int(usage["completion_tokens"])
                        choices = item.get("choices") or []
                        delta = choices[0].get("delta", {}) if choices else {}
                        text = delta.get("content") or ""
                        if text:
                            yield {"type": "chunk", "text": text}
            yield {"type": "done", "tokens": total_tokens, "usage_source": "provider" if total_tokens is not None else "unknown"}
        except httpx.TimeoutException:
            yield {"type": "error", "code": "execution_timeout", "text": "Provider request timed out."}
        except httpx.HTTPError:
            yield {"type": "error", "code": "provider_connection_failed", "text": "Provider connection failed."}
