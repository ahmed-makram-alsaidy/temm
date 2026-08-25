import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path


MAX_RPC_BYTES = 256 * 1024


def load_handler(entrypoint: Path):
    spec = importlib.util.spec_from_file_location("aifleet_plugin_entrypoint", entrypoint)
    if not spec or not spec.loader:
        raise RuntimeError("Plugin entrypoint cannot be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = getattr(module, "handle", None)
    if not callable(handler):
        raise RuntimeError("Plugin entrypoint must export handle(request).")
    return handler


async def invoke(handler, request):
    result = handler(request)
    if inspect.isawaitable(result):
        result = await result
    json.dumps(result)
    return result


async def main() -> int:
    if len(sys.argv) != 3:
        return 2
    entrypoint = Path(sys.argv[1]).resolve(strict=True)
    allowed_methods = set(sys.argv[2].split(","))
    raw = sys.stdin.buffer.readline(MAX_RPC_BYTES + 1)
    if not raw or len(raw) > MAX_RPC_BYTES:
        print(json.dumps({"ok": False, "error": {"code": "rpc_request_invalid", "message": "RPC request is missing or too large."}}))
        return 3
    try:
        request = json.loads(raw)
        if not isinstance(request, dict) or not isinstance(request.get("method"), str) or not isinstance(request.get("params", {}), dict):
            raise ValueError("RPC request must contain method and object params.")
        if request["method"] not in allowed_methods:
            raise PermissionError("RPC method is not declared by the plugin manifest.")
        handler = load_handler(entrypoint)
        result = await invoke(handler, request)
        response = {"ok": True, "request_id": request.get("request_id"), "result": result}
    except Exception as exc:
        response = {"ok": False, "error": {"code": "plugin_runtime_error", "message": str(exc)[:500]}}
    encoded = json.dumps(response)
    if len(encoded.encode()) > MAX_RPC_BYTES:
        encoded = json.dumps({"ok": False, "error": {"code": "rpc_response_too_large", "message": "Plugin response exceeds 256 KiB."}})
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
