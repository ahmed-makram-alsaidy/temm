import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import select

from ..discovery import DiscoveryAdapter, DiscoveryManifestLoader, DiscoveryState
from ..discovery.adapters import expand_location
from ..discovery.services import NullRuntimeServiceProbe, OllamaServiceProbe, RuntimeServiceProbe
from ..storage.database import AsyncSessionLocal
from ..services.audit import audit_service
from ..storage.models import AgentRecord
from ..storage.secret_vault import secret_vault
from .process_manager import ProcessManager, process_manager


class ExecutableResolver:
    def __init__(self, which: Callable[[str], Optional[str]] = shutil.which):
        self._which = which

    def resolve(self, adapter: DiscoveryAdapter) -> Optional[Dict[str, Any]]:
        candidates: List[tuple[str, str]] = []
        for executable in adapter.executable_names:
            located = self._which(executable)
            if located:
                candidates.append((located, "path"))
        for location in adapter.common_locations:
            candidate = expand_location(location)
            if candidate.is_file():
                candidates.append((str(candidate), "common_location"))
        seen = set()
        for value, source in candidates:
            path = Path(value).expanduser()
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            key = os.path.normcase(str(resolved))
            if key in seen or not resolved.is_file():
                continue
            seen.add(key)
            extension = resolved.suffix.lower()
            return {
                "path": str(resolved),
                "source": source,
                "shim": extension in {".cmd", ".bat", ".ps1"},
                "extension": extension,
            }
        return None

    def resolve_manual(self, executable: str) -> Optional[Dict[str, Any]]:
        value = executable.strip().strip('"')
        if not value or "\x00" in value or "\r" in value or "\n" in value:
            return None
        if Path(value).name != value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                return None
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                return None
            if not resolved.is_file():
                return None
            extension = resolved.suffix.lower()
            return {
                "path": str(resolved),
                "source": "manual_path",
                "shim": extension in {".cmd", ".bat", ".ps1"},
                "extension": extension,
            }
        located = self._which(value)
        if not located:
            return None
        return self.resolve_manual(str(Path(located).resolve()))


class SystemScanner:
    def __init__(
        self,
        adapters: Optional[Sequence[DiscoveryAdapter]] = None,
        resolver: Optional[ExecutableResolver] = None,
        manager: Optional[ProcessManager] = None,
        runtime_probe: Optional[RuntimeServiceProbe] = None,
    ):
        self._adapters = list(adapters) if adapters is not None else DiscoveryManifestLoader().load()
        self._resolver = resolver or ExecutableResolver()
        self._manager = manager or process_manager
        self._runtime_probe = runtime_probe or OllamaServiceProbe(secret_vault)

    @property
    def adapters(self) -> List[DiscoveryAdapter]:
        return list(self._adapters)

    async def inspect_runtime_service(self) -> Dict[str, Any]:
        return await self._runtime_probe.inspect()

    async def scan_system(self, persist: bool = True, check_services: bool = True) -> Dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        results = []
        seen_paths = set()
        for adapter in self._adapters:
            result = await self._inspect_adapter(adapter, checked_at)
            path_key = os.path.normcase(result.get("path") or "")
            if path_key and path_key in seen_paths:
                result["state"] = DiscoveryState.UNVERIFIED.value
                result["evidence"]["reason"] = "duplicate_executable_path"
            elif path_key:
                seen_paths.add(path_key)
            results.append(result)

        if persist:
            await self._sync_database(results, checked_at)
        ollama_status = await self._runtime_probe.inspect() if check_services else await NullRuntimeServiceProbe().inspect()
        return {
            "scan_id": f"scan-{uuid.uuid4().hex[:12]}",
            "checked_at": checked_at.isoformat(),
            "discovered_tools": results,
            "summary": {state.value: sum(item["state"] == state.value for item in results) for state in DiscoveryState},
            "ollama_status": ollama_status,
            "configured_providers": secret_vault.list_configured_providers(),
            "total_discovered": sum(item["state"] != DiscoveryState.UNAVAILABLE.value for item in results),
        }

    async def inspect_manual(
        self,
        executable: str,
        version_args: Sequence[str],
        timeout_seconds: float,
        version_pattern: Optional[str] = None,
        health_args: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        resolved = self._resolver.resolve_manual(executable)
        if not resolved:
            return self._unavailable_result("manual", executable, checked_at, "invalid_or_missing_executable")
        return await self._probe(
            adapter_id="manual",
            display_name=Path(resolved["path"]).stem,
            kind="agent",
            capabilities=[],
            resolved=resolved,
            version_args=list(version_args),
            timeout_seconds=timeout_seconds,
            version_pattern=version_pattern,
            checked_at=checked_at,
            source="manual",
            health_args=list(health_args or []),
        )

    async def rescan_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            record = await session.get(AgentRecord, agent_id)
            if not record:
                return None
            if record.discovery_source == "manifest":
                adapter = next((item for item in self._adapters if item.adapter_id == record.adapter_id or item.adapter_id == record.id), None)
                if not adapter:
                    return None
                result = await self._inspect_adapter(adapter, datetime.now(timezone.utc))
                await self._sync_database([result], datetime.now(timezone.utc))
                refreshed = await session.get(AgentRecord, agent_id)
                await audit_service.append(session, action="agent.rescanned", resource_type="agent", resource_id=agent_id, outcome=result["state"], details={"actor": "local_system", "discovery_state": result["state"], "revision": refreshed.revision if refreshed else None})
                await session.commit()
                return result
            version_args = _loads(record.version_probe_args)
            result = await self.inspect_manual(
                record.detected_path or record.cli_command,
                version_args,
                record.probe_timeout_seconds,
                health_args=_loads(record.health_probe_args),
            )
            self._apply_result(record, result, datetime.now(timezone.utc))
            record.revision = (record.revision or 0) + 1
            await audit_service.append(session, action="agent.rescanned", resource_type="agent", resource_id=agent_id, outcome=result["state"], details={"actor": "local_system", "discovery_state": result["state"], "revision": record.revision})
            await session.commit()
            return result

    async def probe_auth(self, record: AgentRecord) -> Dict[str, Any]:
        if record.auth_state == "not_required":
            return {"state": "not_required", "method": "none", "evidence": {"required": False}}
        args = _loads(record.auth_probe_args)
        parser = _load_object(record.auth_probe_parser)
        if not args or not parser:
            return {"state": "unknown", "method": record.auth_method, "evidence": {"reason": "auth_probe_not_configured"}}
        executable = record.detected_path or record.cli_command
        receipt = await self._manager.execute_argv(
            [executable, *args],
            task_id=f"discovery-auth-{record.id}-{uuid.uuid4().hex[:10]}",
            timeout_seconds=record.probe_timeout_seconds,
        )
        output = (receipt["stdout"] or receipt["stderr"]).strip()
        evidence = {
            "source": "auth_probe",
            "outcome": receipt["outcome"],
            "exit_code": receipt["exit_code"],
            "duration_ms": receipt["duration_ms"],
        }
        if not receipt["success"]:
            evidence["reason"] = receipt["error_code"] or receipt["outcome"]
            return {"state": "failed", "method": record.auth_method, "evidence": evidence}
        verified = _evaluate_auth_parser(parser, output)
        evidence["verified"] = verified
        if not verified:
            evidence["reason"] = "auth_evidence_not_matched"
        return {"state": "verified" if verified else "failed", "method": record.auth_method, "evidence": evidence}

    async def _inspect_adapter(self, adapter: DiscoveryAdapter, checked_at: datetime) -> Dict[str, Any]:
        resolved = self._resolver.resolve(adapter)
        if not resolved:
            return self._unavailable_result(
                adapter.adapter_id,
                adapter.executable_names[0],
                checked_at,
                "executable_not_found",
                adapter,
            )
        return await self._probe(
            adapter_id=adapter.adapter_id,
            display_name=adapter.display_name,
            kind=adapter.kind.value,
            capabilities=list(adapter.capabilities),
            resolved=resolved,
            version_args=list(adapter.version_args),
            timeout_seconds=adapter.timeout_seconds,
            version_pattern=adapter.version_pattern,
            checked_at=checked_at,
            source="manifest",
            adapter=adapter,
            health_args=list(adapter.health_args),
        )

    async def _probe(
        self,
        adapter_id: str,
        display_name: str,
        kind: str,
        capabilities: List[str],
        resolved: Dict[str, Any],
        version_args: List[str],
        timeout_seconds: float,
        version_pattern: Optional[str],
        checked_at: datetime,
        source: str,
        adapter: Optional[DiscoveryAdapter] = None,
        health_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        evidence = {
            "path_source": resolved["source"],
            "resolved_path": resolved["path"],
            "shim": resolved["shim"],
            "probe_args": version_args,
            "probe_timeout_seconds": timeout_seconds,
        }
        base = {
            "id": adapter_id,
            "name": display_name,
            "kind": kind,
            "path": resolved["path"],
            "binary": Path(resolved["path"]).name,
            "capabilities": capabilities,
            "checked_at": checked_at.isoformat(),
            "source": source,
            "evidence": evidence,
            "version": "",
            "is_installed": True,
            "supports_pty": "pty" in capabilities,
            "supports_interactive": "interactive" in capabilities and "pty" in capabilities,
            "input_method": adapter.input_method if adapter else "argument",
            "output_method": adapter.output_method if adapter else "stdout",
            "working_directory": adapter.working_directory if adapter else "workspace",
            "invocation_args": list(adapter.invocation_args) if adapter else [],
            "health_probe_args": list(adapter.health_args) if adapter else [],
            "probe_timeout_seconds": timeout_seconds,
        }
        if not version_args:
            return {**base, "state": DiscoveryState.DETECTED.value}
        task_id = f"discovery-{adapter_id}-{uuid.uuid4().hex[:10]}"
        receipt = await self._manager.execute_argv(
            [resolved["path"], *version_args],
            task_id=task_id,
            timeout_seconds=timeout_seconds,
        )
        output = (receipt["stdout"] or receipt["stderr"]).strip()
        evidence.update({
            "receipt_outcome": receipt["outcome"],
            "exit_code": receipt["exit_code"],
            "duration_ms": receipt["duration_ms"],
            "output_excerpt": output[:240],
        })
        if not receipt["success"]:
            evidence["reason"] = receipt["error_code"] or receipt["outcome"]
            return {**base, "state": DiscoveryState.BROKEN.value}
        first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
        if not first_line:
            evidence["reason"] = "empty_probe_output"
            return {**base, "state": DiscoveryState.UNVERIFIED.value}
        if version_pattern:
            import re

            match = re.search(version_pattern, output)
            if not match:
                evidence["reason"] = "version_output_not_recognized"
                return {**base, "state": DiscoveryState.UNVERIFIED.value}
        if health_args:
            health_receipt = await self._manager.execute_argv(
                [resolved["path"], *health_args],
                task_id=f"discovery-health-{adapter_id}-{uuid.uuid4().hex[:10]}",
                timeout_seconds=timeout_seconds,
            )
            evidence["health"] = {
                "args": health_args,
                "outcome": health_receipt["outcome"],
                "exit_code": health_receipt["exit_code"],
                "duration_ms": health_receipt["duration_ms"],
            }
            if not health_receipt["success"]:
                evidence["reason"] = "health_probe_failed"
                return {**base, "state": DiscoveryState.BROKEN.value, "version": first_line[:128]}
        return {**base, "state": DiscoveryState.VERIFIED.value, "version": first_line[:128]}

    def _unavailable_result(
        self,
        adapter_id: str,
        binary: str,
        checked_at: datetime,
        reason: str,
        adapter: Optional[DiscoveryAdapter] = None,
    ) -> Dict[str, Any]:
        return {
            "id": adapter_id,
            "name": adapter.display_name if adapter else binary,
            "kind": adapter.kind.value if adapter else "agent",
            "binary": binary,
            "path": "",
            "version": "",
            "state": DiscoveryState.UNAVAILABLE.value,
            "is_installed": False,
            "capabilities": list(adapter.capabilities) if adapter else [],
            "supports_pty": False,
            "supports_interactive": False,
            "input_method": adapter.input_method if adapter else "argument",
            "output_method": adapter.output_method if adapter else "stdout",
            "working_directory": adapter.working_directory if adapter else "workspace",
            "invocation_args": list(adapter.invocation_args) if adapter else [],
            "health_probe_args": list(adapter.health_args) if adapter else [],
            "probe_timeout_seconds": adapter.timeout_seconds if adapter else 3.0,
            "checked_at": checked_at.isoformat(),
            "source": "manifest" if adapter else "manual",
            "evidence": {"reason": reason},
        }

    async def _sync_database(self, results: List[Dict[str, Any]], checked_at: datetime) -> None:
        async with AsyncSessionLocal() as session:
            existing = {item.id: item for item in (await session.execute(select(AgentRecord))).scalars().all()}
            adapter_by_id = {adapter.adapter_id: adapter for adapter in self._adapters}
            for result in results:
                adapter = adapter_by_id[result["id"]]
                record = existing.get(result["id"])
                if not record:
                    record = AgentRecord(
                        id=result["id"],
                        name=adapter.display_name,
                        cli_command=adapter.executable_names[0],
                        description=f"Discovered through adapter {adapter.adapter_id}.",
                    )
                    session.add(record)
                record.name = adapter.display_name
                record.adapter_id = adapter.adapter_id
                record.tool_kind = adapter.kind.value
                record.discovery_source = "manifest"
                self._apply_result(record, result, checked_at)
                record.version_probe_args = _json(list(adapter.version_args))
                record.health_probe_args = _json(list(adapter.health_args))
                record.invocation_args = _json(list(adapter.invocation_args))
                record.probe_timeout_seconds = adapter.timeout_seconds
                record.revision = (record.revision or 0) + 1
                if not adapter.auth_required:
                    record.auth_state = "not_required"
                    record.auth_method = "none"
                    record.auth_evidence = _json({"source": "manifest", "required": False})
                    record.auth_checked_at = None
                elif record.auth_state in {None, "", "not_required"}:
                    record.auth_state = "unknown"
                    record.auth_method = adapter.auth_method
                    record.auth_evidence = _json({"source": "manifest", "verified": False})
                    record.auth_checked_at = None
                record.auth_setup_action = _json({"type": "instructions", "instructions": adapter.auth_setup_instructions} if adapter.auth_setup_instructions else {})
                record.auth_probe_args = _json(list(adapter.auth_probe_args))
                record.auth_probe_parser = _json(adapter.auth_probe_parser)
            await session.commit()

    def _apply_result(self, record: AgentRecord, result: Dict[str, Any], checked_at: datetime) -> None:
        record.discovery_state = result["state"]
        record.discovery_evidence = _json(result["evidence"])
        record.last_checked_at = checked_at.replace(tzinfo=None)
        record.detected_path = result["path"]
        record.version = result["version"]
        record.is_installed = result["is_installed"]
        record.status = "ready" if result["state"] == DiscoveryState.VERIFIED.value else result["state"]
        if record.discovery_source == "manifest":
            record.capabilities = _json(result["capabilities"])
            record.supports_pty = result["supports_pty"]
            record.supports_interactive = result["supports_interactive"]
            record.input_method = result["input_method"]
            record.output_method = result["output_method"]
            record.working_directory = result["working_directory"]

def _json(value: Any) -> str:
    import json

    return json.dumps(value)


def _evaluate_auth_parser(parser: Dict[str, Any], output: str) -> bool:
    import re

    parser_type = parser.get("type")
    if parser_type == "exit_zero":
        return True
    if parser_type == "output_regex":
        pattern = parser.get("pattern")
        return bool(isinstance(pattern, str) and re.search(pattern, output))
    if parser_type == "json_field":
        try:
            value: Any = __import__("json").loads(output)
        except (ValueError, TypeError):
            return False
        path = parser.get("path")
        if not isinstance(path, str) or not path:
            return False
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        return value == parser.get("equals")
    return False


def _load_object(value: Any) -> Dict[str, Any]:
    import json

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _loads(value: Any) -> List[str]:
    import json

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


system_scanner = SystemScanner()
