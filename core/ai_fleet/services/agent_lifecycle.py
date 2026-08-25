import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..discovery.adapters import ALLOWED_CAPABILITIES, validate_probe_args
from ..engine.scanner import SystemScanner
from ..errors import DomainError
from ..storage.models import AgentRecord, TaskRun
from ..storage.secret_vault import SecretVault
from .audit import audit_service


AUTH_METHODS = {"none", "account", "api_key", "account_or_api_key", "provider_credentials", "environment", "custom"}


class AgentLifecycleError(DomainError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(code, message=message, status_code=status_code, retryable=code == "stale_agent_revision")
        self.message = message

    def detail(self) -> Dict[str, Any]:
        return self.payload()


class AgentLifecycleService:
    def __init__(self, scanner: SystemScanner, vault: SecretVault):
        self._scanner = scanner
        self._vault = vault

    async def create(self, session: AsyncSession, values: Dict[str, Any]) -> AgentRecord:
        config = self._validate_configuration(values)
        inspection = await self._scanner.inspect_manual(
            executable=values["executable"],
            version_args=config["version_args"],
            timeout_seconds=values["probe_timeout_seconds"],
            health_args=config["health_args"],
        )
        self._ensure_available(inspection)
        await self._ensure_unique_path(session, inspection["path"])
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        auth = self._derive_auth(values["auth_required"], values["auth_method"], values.get("auth_setup_instructions", ""))
        state = inspection["state"]
        record = AgentRecord(
            id=agent_id,
            name=values["name"].strip(),
            cli_command=inspection["path"],
            version_command="",
            prompt_arg_format="{prompt}",
            workspace_arg_format="",
            input_method=values["input_method"],
            output_method=values["output_method"],
            supports_pty=values["supports_pty"],
            supports_interactive=values["supports_interactive"],
            capabilities=json.dumps(config["capabilities"]),
            tool_kind="agent",
            adapter_id=f"manual:{agent_id}",
            discovery_state=state,
            discovery_source="manual",
            discovery_evidence=json.dumps(inspection["evidence"]),
            version_probe_args=json.dumps(config["version_args"]),
            health_probe_args=json.dumps(config["health_args"]),
            invocation_args=json.dumps(config["invocation_args"]),
            environment_refs=json.dumps(config["environment_refs"]),
            working_directory=values["working_directory"],
            probe_timeout_seconds=values["probe_timeout_seconds"],
            permission_profile=values["permission_profile"],
            auth_state=auth["state"],
            auth_method=auth["method"],
            auth_evidence=json.dumps(auth["evidence"]),
            auth_setup_action=json.dumps(auth["setup_action"]),
            description=values.get("description", ""),
            is_installed=True,
            detected_path=inspection["path"],
            version=inspection["version"],
            status="ready" if state == "verified" else state,
            last_checked_at=self._now(),
        )
        session.add(record)
        await audit_service.append(session, action="agent.created", resource_type="agent", resource_id=record.id, details={"actor": "local_system", "source": "manual", "discovery_state": state, "revision": record.revision})
        await session.commit()
        return record

    async def update(self, session: AsyncSession, agent_id: str, changes: Dict[str, Any], expected_revision: int) -> AgentRecord:
        record = await self._get(session, agent_id)
        if record.revision != expected_revision:
            raise AgentLifecycleError(409, "stale_agent_revision", f"Agent changed since revision {expected_revision}; current revision is {record.revision}.")
        if record.discovery_source != "manual":
            unsupported = set(changes) - {"user_enabled"}
            if unsupported:
                raise AgentLifecycleError(409, "managed_agent", "Manifest-managed Agents can only be enabled or disabled.")
            if "user_enabled" in changes:
                record.user_enabled = changes["user_enabled"]
            self._bump(record)
            action = "agent.enabled" if changes.get("user_enabled") is True else "agent.disabled" if changes.get("user_enabled") is False else "agent.updated"
            await audit_service.append(session, action=action, resource_type="agent", resource_id=record.id, details={"actor": "local_system", "fields": sorted(changes), "revision": record.revision})
            await session.commit()
            return record

        metadata_fields = {"name", "description", "user_enabled", "auth_required", "auth_method", "auth_setup_instructions"}
        if set(changes).issubset(metadata_fields):
            self._apply_metadata(record, changes)
            self._bump(record)
            action = "agent.enabled" if changes.get("user_enabled") is True else "agent.disabled" if changes.get("user_enabled") is False else "agent.updated"
            await audit_service.append(session, action=action, resource_type="agent", resource_id=record.id, details={"actor": "local_system", "fields": sorted(changes), "revision": record.revision})
            await session.commit()
            return record

        values = self._merged_values(record, changes)
        config = self._validate_configuration(values)
        inspection = await self._scanner.inspect_manual(
            executable=values["executable"],
            version_args=config["version_args"],
            health_args=config["health_args"],
            timeout_seconds=values["probe_timeout_seconds"],
        )
        self._ensure_available(inspection)
        await self._ensure_unique_path(session, inspection["path"], agent_id)
        state = inspection["state"]
        record.name = values["name"].strip()
        record.cli_command = inspection["path"]
        record.detected_path = inspection["path"]
        record.version = inspection["version"]
        record.discovery_state = state
        record.discovery_evidence = json.dumps(inspection["evidence"])
        record.last_checked_at = self._now()
        record.status = "ready" if state == "verified" else state
        record.version_probe_args = json.dumps(config["version_args"])
        record.health_probe_args = json.dumps(config["health_args"])
        record.invocation_args = json.dumps(config["invocation_args"])
        record.input_method = values["input_method"]
        record.output_method = values["output_method"]
        record.working_directory = values["working_directory"]
        record.supports_pty = values["supports_pty"]
        record.supports_interactive = values["supports_interactive"]
        record.capabilities = json.dumps(config["capabilities"])
        record.environment_refs = json.dumps(config["environment_refs"])
        record.permission_profile = values["permission_profile"]
        record.probe_timeout_seconds = values["probe_timeout_seconds"]
        record.description = values["description"]
        record.user_enabled = values["user_enabled"]
        self._apply_auth(record, values, changes)
        record.lifecycle_status = "active"
        self._bump(record)
        await audit_service.append(session, action="agent.updated", resource_type="agent", resource_id=record.id, details={"actor": "local_system", "fields": sorted(changes), "discovery_state": state, "revision": record.revision})
        await session.commit()
        return record

    async def remove(self, session: AsyncSession, agent_id: str) -> Dict[str, Any]:
        record = await self._get(session, agent_id)
        if record.discovery_source != "manual":
            raise AgentLifecycleError(409, "managed_agent", "Manifest-managed inventory cannot be deleted; disable it instead.")
        referenced = (await session.execute(select(TaskRun.id).where(TaskRun.selected_agent_id == agent_id).limit(1))).scalar_one_or_none()
        self._delete_bound_secrets(record)
        if referenced:
            record.user_enabled = False
            record.lifecycle_status = "retired"
            if record.auth_state == "configured":
                record.auth_state = "unknown"
                record.auth_evidence = json.dumps({"source": "secret_reference", "configured": False, "verified": False})
            self._bump(record)
            await audit_service.append(session, action="agent.retired", resource_type="agent", resource_id=agent_id, details={"actor": "local_system", "history_preserved": True, "revision": record.revision})
            await session.commit()
            return {"agent_id": agent_id, "deleted": False, "retired": True, "history_preserved": True}
        await audit_service.append(session, action="agent.deleted", resource_type="agent", resource_id=agent_id, details={"actor": "local_system", "history_preserved": True, "revision": record.revision})
        await session.delete(record)
        await session.commit()
        return {"agent_id": agent_id, "deleted": True, "retired": False, "history_preserved": True}

    async def rescan(self, agent_id: str) -> Dict[str, Any]:
        result = await self._scanner.rescan_agent(agent_id)
        if result is None:
            raise AgentLifecycleError(404, "agent_not_found", "Agent or discovery adapter not found.")
        return result

    async def check_auth(self, session: AsyncSession, agent_id: str) -> Dict[str, Any]:
        record = await self._get(session, agent_id)
        result = await self._scanner.probe_auth(record)
        record.auth_state = result["state"]
        record.auth_method = result["method"]
        record.auth_evidence = json.dumps(result["evidence"])
        record.auth_checked_at = self._now()
        self._bump(record)
        await audit_service.append(session, action="agent.auth_checked", resource_type="agent", resource_id=agent_id, outcome=record.auth_state, details={"actor": "local_system", "auth_state": record.auth_state, "auth_method": record.auth_method, "revision": record.revision})
        await session.commit()
        return {
            "agent_id": agent_id,
            "auth_state": record.auth_state,
            "auth_method": record.auth_method,
            "auth_evidence": result["evidence"],
            "auth_checked_at": record.auth_checked_at.isoformat(),
            "revision": record.revision,
        }

    async def list_secrets(self, session: AsyncSession, agent_id: str) -> List[Dict[str, Any]]:
        record = await self._get(session, agent_id)
        return [
            {"reference": reference, "configured": self._vault.has_key(self._secret_key(record.id, reference))}
            for reference in self._list(record.secret_refs)
        ]

    async def set_secret(self, session: AsyncSession, agent_id: str, reference: str, value: str) -> Dict[str, Any]:
        record = await self._get(session, agent_id)
        normalized = reference.strip().upper()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", normalized):
            raise AgentLifecycleError(422, "invalid_secret_reference", "Secret reference must be an uppercase symbolic name.")
        self._vault.set_key(self._secret_key(agent_id, normalized), value)
        references = self._list(record.secret_refs)
        if normalized not in references:
            references.append(normalized)
            record.secret_refs = json.dumps(references)
        if record.auth_state not in {"not_required", "verified"}:
            record.auth_state = "configured"
            record.auth_evidence = json.dumps({"source": "secret_reference", "configured": True, "verified": False})
            record.auth_checked_at = None
        self._bump(record)
        await audit_service.append(session, action="agent.secret_configured", resource_type="agent", resource_id=agent_id, details={"actor": "local_system", "reference": normalized, "configured": True, "revision": record.revision})
        await session.commit()
        return {"agent_id": agent_id, "reference": normalized, "configured": True, "auth_state": record.auth_state, "revision": record.revision}

    async def delete_secret(self, session: AsyncSession, agent_id: str, reference: str) -> Dict[str, Any]:
        record = await self._get(session, agent_id)
        normalized = reference.strip().upper()
        references = self._list(record.secret_refs)
        if normalized not in references:
            raise AgentLifecycleError(404, "secret_reference_not_found", "Secret reference not found.")
        self._vault.delete_key(self._secret_key(agent_id, normalized))
        references.remove(normalized)
        record.secret_refs = json.dumps(references)
        if record.auth_state == "configured" and not references:
            record.auth_state = "unknown"
            record.auth_evidence = json.dumps({"source": "secret_reference", "configured": False, "verified": False})
            record.auth_checked_at = None
        self._bump(record)
        await audit_service.append(session, action="agent.secret_removed", resource_type="agent", resource_id=agent_id, details={"actor": "local_system", "reference": normalized, "configured": False, "revision": record.revision})
        await session.commit()
        return {"agent_id": agent_id, "reference": normalized, "configured": False, "auth_state": record.auth_state, "revision": record.revision}

    def _validate_configuration(self, values: Dict[str, Any]) -> Dict[str, Any]:
        try:
            version_args = validate_probe_args(values["version_probe_args"])
            health_args = validate_probe_args(values["health_probe_args"])
            invocation_args = validate_probe_args(values["invocation_args"])
        except ValueError as exc:
            raise AgentLifecycleError(422, "invalid_arguments", str(exc)) from exc
        capabilities = list(dict.fromkeys(values["capabilities"]))
        if values["supports_pty"] and "pty" not in capabilities:
            capabilities.append("pty")
        if values["supports_interactive"] and "interactive" not in capabilities:
            capabilities.append("interactive")
        if values["input_method"] == "stdin" and "stdin" not in capabilities:
            capabilities.append("stdin")
        if set(capabilities) - ALLOWED_CAPABILITIES:
            raise AgentLifecycleError(422, "invalid_capability", "One or more capabilities are unsupported.")
        if values["input_method"] not in {"argument", "stdin"} or values["output_method"] not in {"stdout", "json"}:
            raise AgentLifecycleError(422, "invalid_io_method", "Unsupported input or output method.")
        if values["working_directory"] not in {"workspace", "inherit"}:
            raise AgentLifecycleError(422, "invalid_working_directory", "Unsupported working directory behavior.")
        if values["permission_profile"] not in {"safe", "developer", "full"}:
            raise AgentLifecycleError(422, "invalid_permission_profile", "Unsupported permission profile.")
        refs = list(dict.fromkeys(values["environment_refs"]))
        if any(not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", item) for item in refs):
            raise AgentLifecycleError(422, "invalid_environment_reference", "Environment references must be variable names, not values.")
        if values["supports_interactive"] and not values["supports_pty"]:
            raise AgentLifecycleError(422, "interactive_requires_pty", "Interactive execution requires PTY support.")
        if values["auth_method"] not in AUTH_METHODS or (values["auth_required"] and values["auth_method"] == "none"):
            raise AgentLifecycleError(422, "invalid_auth_method", "Unsupported authentication method.")
        return {
            "version_args": version_args,
            "health_args": health_args,
            "invocation_args": invocation_args,
            "capabilities": capabilities,
            "environment_refs": refs,
        }

    def _merged_values(self, record: AgentRecord, changes: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": changes.get("name", record.name),
            "executable": changes.get("executable", record.detected_path or record.cli_command),
            "version_probe_args": changes.get("version_probe_args", self._list(record.version_probe_args)),
            "health_probe_args": changes.get("health_probe_args", self._list(record.health_probe_args)),
            "invocation_args": changes.get("invocation_args", self._list(record.invocation_args)),
            "input_method": changes.get("input_method", record.input_method),
            "output_method": changes.get("output_method", record.output_method),
            "working_directory": changes.get("working_directory", record.working_directory),
            "supports_pty": changes.get("supports_pty", record.supports_pty),
            "supports_interactive": changes.get("supports_interactive", record.supports_interactive),
            "capabilities": changes.get("capabilities", self._list(record.capabilities)),
            "environment_refs": changes.get("environment_refs", self._list(record.environment_refs)),
            "probe_timeout_seconds": changes.get("probe_timeout_seconds", record.probe_timeout_seconds),
            "permission_profile": changes.get("permission_profile", record.permission_profile),
            "description": changes.get("description", record.description),
            "user_enabled": changes.get("user_enabled", record.user_enabled),
            "auth_required": changes.get("auth_required", record.auth_state != "not_required"),
            "auth_method": changes.get("auth_method", record.auth_method),
            "auth_setup_instructions": changes.get("auth_setup_instructions", self._setup_instructions(record)),
        }

    def _apply_metadata(self, record: AgentRecord, changes: Dict[str, Any]) -> None:
        if "name" in changes:
            record.name = changes["name"].strip()
        if "description" in changes:
            record.description = changes["description"]
        if "user_enabled" in changes:
            record.user_enabled = changes["user_enabled"]
        self._apply_auth(record, self._merged_values(record, changes), changes)

    def _apply_auth(self, record: AgentRecord, values: Dict[str, Any], changes: Dict[str, Any]) -> None:
        if not ({"auth_required", "auth_method", "auth_setup_instructions"} & set(changes)):
            return
        auth = self._derive_auth(values["auth_required"], values["auth_method"], values["auth_setup_instructions"])
        record.auth_state = auth["state"]
        record.auth_method = auth["method"]
        record.auth_evidence = json.dumps(auth["evidence"])
        record.auth_setup_action = json.dumps(auth["setup_action"])
        record.auth_checked_at = None

    def _derive_auth(self, required: bool, method: str, instructions: str) -> Dict[str, Any]:
        if method not in AUTH_METHODS or (required and method == "none"):
            raise AgentLifecycleError(422, "invalid_auth_method", "Unsupported authentication method.")
        return {
            "state": "unknown" if required else "not_required",
            "method": method if required else "none",
            "evidence": {"source": "user_configuration", "verified": False} if required else {"source": "configuration", "required": False},
            "setup_action": {"type": "instructions", "instructions": instructions} if instructions else {},
        }

    async def _get(self, session: AsyncSession, agent_id: str) -> AgentRecord:
        record = await session.get(AgentRecord, agent_id)
        if not record:
            raise AgentLifecycleError(404, "agent_not_found", "Agent not found.")
        return record

    async def _ensure_unique_path(self, session: AsyncSession, path: str, exclude_id: Optional[str] = None) -> None:
        statement = select(AgentRecord).where(AgentRecord.detected_path == path)
        if exclude_id:
            statement = statement.where(AgentRecord.id != exclude_id)
        duplicate = (await session.execute(statement)).scalar_one_or_none()
        if duplicate:
            raise AgentLifecycleError(409, "duplicate_executable", f"{duplicate.name} already uses this executable.")

    def _ensure_available(self, inspection: Dict[str, Any]) -> None:
        if inspection["state"] == "unavailable":
            raise AgentLifecycleError(422, "invalid_executable", "Executable was not found or is not a valid file.")

    def _delete_bound_secrets(self, record: AgentRecord) -> None:
        for reference in self._list(record.secret_refs):
            self._vault.delete_key(self._secret_key(record.id, reference))
        record.secret_refs = "[]"

    def _setup_instructions(self, record: AgentRecord) -> str:
        action = self._object(record.auth_setup_action)
        return str(action.get("instructions") or "")

    def _secret_key(self, agent_id: str, reference: str) -> str:
        return f"agent:{agent_id}:{reference.lower()}"

    def _list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def _object(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def _bump(self, record: AgentRecord) -> None:
        record.revision = (record.revision or 0) + 1

    def _now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)
