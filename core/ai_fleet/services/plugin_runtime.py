import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..engine.process_manager import ProcessManager
from ..errors import DomainError
from ..plugin_package import PluginPackageError, contained_entrypoint, hash_plugin_folder
from ..plugin_permissions import plugin_permission_policy
from ..plugin_protocol import PluginManifest, negotiate_protocol
from ..storage.models import PluginRecord
from .audit import audit_service


MAX_RPC_BYTES = 256 * 1024


class PluginRuntimeService:
    def __init__(self, manager: ProcessManager):
        self._manager = manager

    async def invoke(self, session: AsyncSession, plugin_id: str, method: str, params: Dict[str, Any], timeout_seconds: float = 30) -> Dict[str, Any]:
        record = await session.get(PluginRecord, plugin_id)
        if not record:
            raise DomainError("resource_not_found", message="Plugin was not found.")
        if record.load_state not in {"eligible", "ready"}:
            raise DomainError("execution_unavailable", message="Plugin is not eligible for execution.")
        try:
            manifest = PluginManifest.parse(json.loads(record.manifest))
            if not negotiate_protocol(manifest.protocol):
                record.load_state = "incompatible"
                await session.commit()
                raise DomainError("execution_unavailable", message="Plugin protocol is incompatible with this Core version.")
            folder = Path(record.path).resolve(strict=True)
            entrypoint = contained_entrypoint(folder, manifest.entrypoint)
            current_hash = hash_plugin_folder(folder)
            plugin_permission_policy.enforce(manifest, record.permission_profile, json.loads(record.granted_permissions or "[]"))
            if method not in manifest.rpc_methods:
                raise PermissionError(f"Plugin does not declare RPC method: {method}")
        except DomainError:
            raise
        except (ValueError, OSError, PluginPackageError, PermissionError) as exc:
            record.load_state = "invalid"
            await session.commit()
            raise DomainError("execution_unavailable", message=str(exc)) from exc
        if current_hash != record.package_hash:
            record.load_state = "changed"
            await session.commit()
            raise DomainError("execution_unavailable", message="Plugin package changed after approval; inspect and approve it again.")
        request = {"request_id": f"rpc-{uuid.uuid4().hex}", "method": method, "params": params}
        encoded = json.dumps(request)
        if len(encoded.encode()) > MAX_RPC_BYTES:
            raise DomainError("validation_failed", message="Plugin RPC request exceeds 256 KiB.")
        task_id = f"plugin-{plugin_id}-{uuid.uuid4().hex[:10]}"
        repository_root = str(Path(__file__).resolve().parents[3])
        python_path = repository_root + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
        receipt = await self._manager.execute_argv(
            [sys.executable, "-m", "core.ai_fleet.plugin_host", str(entrypoint), ",".join(sorted(manifest.rpc_methods))],
            task_id=task_id,
            cwd=str(folder),
            env={"PYTHONPATH": python_path, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout_seconds=timeout_seconds,
            stdin_data=encoded + "\n",
        )
        if not receipt["success"]:
            record.load_state = "failed"
            await audit_service.append(session, action="plugin.runtime_failed", resource_type="plugin", resource_id=plugin_id, outcome=receipt["outcome"], details={"error_code": receipt["error_code"]})
            await session.commit()
            raise DomainError("execution_unavailable", message="Plugin process failed.", details={"outcome": receipt["outcome"], "error_code": receipt["error_code"]})
        lines = [line for line in receipt["stdout"].splitlines() if line.strip()]
        if len(lines) != 1:
            record.load_state = "failed"
            await session.commit()
            raise DomainError("internal_error", message="Plugin returned an invalid RPC response.")
        try:
            response = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            record.load_state = "failed"
            await session.commit()
            raise DomainError("internal_error", message="Plugin returned malformed JSON.") from exc
        if not isinstance(response, dict) or response.get("request_id") not in {None, request["request_id"]}:
            raise DomainError("internal_error", message="Plugin RPC response identity is invalid.")
        record.load_state = "ready" if response.get("ok") else "failed"
        await audit_service.append(session, action="plugin.invoked", resource_type="plugin", resource_id=plugin_id, outcome="success" if response.get("ok") else "failed", details={"method": method})
        await session.commit()
        if not response.get("ok"):
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise DomainError("execution_unavailable", message=str(error.get("message") or "Plugin invocation failed."), details={"plugin_error_code": error.get("code")})
        return response

    async def reload(self, session: AsyncSession, plugin_id: str) -> PluginRecord:
        record = await session.get(PluginRecord, plugin_id)
        if not record:
            raise DomainError("resource_not_found", message="Plugin was not found.")
        if any(task_id.startswith(f"plugin-{plugin_id}-") for task_id in self._manager._active):
            raise DomainError("resource_conflict", message="Plugin cannot reload while an invocation is active.")
        try:
            folder = Path(record.path).resolve(strict=True)
            manifest_path = next(path for path in [folder / "manifest.json", folder / "manifest.yaml", folder / "manifest.yml"] if path.exists())
            if manifest_path.suffix == ".json":
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                import yaml
                manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest = PluginManifest.parse(manifest_data)
            if manifest.plugin_id != plugin_id:
                raise ValueError("Plugin identity changed during reload.")
            entrypoint = contained_entrypoint(folder, manifest.entrypoint)
            package_hash = hash_plugin_folder(folder)
            plugin_permission_policy.enforce(manifest, record.permission_profile, json.loads(record.granted_permissions or "[]"))
            compatible = negotiate_protocol(manifest.protocol)
        except Exception as exc:
            raise DomainError("execution_unavailable", message=str(exc)) from exc
        record.manifest = json.dumps(manifest.to_dict())
        record.version = manifest.version
        record.protocol_version = manifest.protocol
        record.plugin_type = manifest.plugin_type.value
        record.permissions = json.dumps(sorted(item.value for item in manifest.permissions))
        record.package_hash = package_hash
        record.entrypoint = str(entrypoint)
        record.load_state = "eligible" if compatible else "incompatible"
        await audit_service.append(session, action="plugin.reloaded", resource_type="plugin", resource_id=plugin_id, details={"version": manifest.version, "package_hash": package_hash, "compatible": compatible})
        await session.commit()
        return record

    async def cancel(self, task_id: str) -> bool:
        return await self._manager.cancel(task_id)
