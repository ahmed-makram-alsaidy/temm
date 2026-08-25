from typing import Any, Dict, Optional

import httpx

from ..storage.secret_vault import SecretVault


class RuntimeServiceProbe:
    async def inspect(self) -> Dict[str, Any]:
        raise NotImplementedError


class OllamaServiceProbe(RuntimeServiceProbe):
    def __init__(self, vault: SecretVault):
        self._vault = vault

    async def inspect(self) -> Dict[str, Any]:
        host = self._vault.get_key("ollama_host") or "http://localhost:11434"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{host}/api/tags")
            if response.status_code == 200:
                payload = response.json()
                models = [
                    {
                        "name": item.get("name"),
                        "size_bytes": item.get("size", 0),
                        "modified_at": item.get("modified_at"),
                    }
                    for item in payload.get("models", [])
                    if item.get("name")
                ]
                return {"running": True, "host": host, "models": models, "evidence": "runtime_api"}
        except Exception:
            pass
        return {"running": False, "host": host, "models": [], "evidence": "unavailable"}


class NullRuntimeServiceProbe(RuntimeServiceProbe):
    async def inspect(self) -> Dict[str, Any]:
        return {"running": False, "host": "", "models": [], "evidence": "not_checked"}
