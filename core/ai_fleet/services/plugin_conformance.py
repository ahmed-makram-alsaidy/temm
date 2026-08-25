import json
import time
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..plugin_package import contained_entrypoint, hash_plugin_folder
from ..plugin_permissions import plugin_permission_policy
from ..plugin_protocol import PluginManifest, negotiate_protocol
from ..storage.models import PluginRecord
from .plugin_runtime import PluginRuntimeService


class PluginConformanceService:
    def __init__(self, runtime: PluginRuntimeService):
        self.runtime = runtime

    async def run(self, session: AsyncSession, plugin_id: str) -> Dict[str, Any]:
        record = await session.get(PluginRecord, plugin_id)
        if not record:
            return {"plugin_id": plugin_id, "passed": False, "checks": [{"name": "registration", "passed": False, "error": "not_found"}]}
        checks: List[Dict[str, Any]] = []
        try:
            manifest = PluginManifest.parse(json.loads(record.manifest))
            checks.append({"name": "manifest", "passed": True})
            compatible = negotiate_protocol(manifest.protocol)
            checks.append({"name": "compatibility", "passed": compatible, "protocol": manifest.protocol})
            folder = Path(record.path)
            entrypoint = contained_entrypoint(folder, manifest.entrypoint)
            unchanged = hash_plugin_folder(folder) == record.package_hash
            checks.append({"name": "package_integrity", "passed": unchanged})
            plugin_permission_policy.enforce(manifest, record.permission_profile, json.loads(record.granted_permissions or "[]"))
            checks.append({"name": "permissions", "passed": True})
        except Exception as exc:
            checks.append({"name": "static_validation", "passed": False, "error": type(exc).__name__})
            return {"plugin_id": plugin_id, "passed": False, "checks": checks}
        if not compatible or not unchanged:
            return {"plugin_id": plugin_id, "passed": False, "checks": checks}
        for method in sorted(manifest.rpc_methods - {"cancel"}):
            started = time.perf_counter()
            try:
                response = await self.runtime.invoke(session, plugin_id, method, {"conformance": True}, timeout_seconds=3)
                checks.append({"name": f"rpc.{method}", "passed": bool(response.get("ok")), "duration_ms": int((time.perf_counter() - started) * 1000)})
            except Exception as exc:
                checks.append({"name": f"rpc.{method}", "passed": False, "duration_ms": int((time.perf_counter() - started) * 1000), "error": type(exc).__name__})
        passed = all(check["passed"] for check in checks)
        return {"plugin_id": plugin_id, "passed": passed, "checks": checks}
