import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List

from .domain import CAPABILITIES


PLUGIN_PROTOCOL_VERSION = "1.0"


def negotiate_protocol(requirement: str, core_version: str = PLUGIN_PROTOCOL_VERSION) -> bool:
    def parse(value: str) -> tuple[int, int]:
        match = re.fullmatch(r"(\d+)\.(\d+)", value.strip())
        if not match:
            raise ValueError("Protocol version is invalid.")
        return int(match.group(1)), int(match.group(2))
    core = parse(core_version)
    if "," not in requirement and not requirement.startswith((">", "<", "=")):
        return parse(requirement) == core
    for clause in requirement.split(","):
        clause = clause.strip()
        match = re.fullmatch(r"(>=|<=|>|<|==)(\d+\.\d+)", clause)
        if not match:
            raise ValueError("Protocol range is invalid.")
        operator, value = match.group(1), parse(match.group(2))
        if operator == ">=" and not core >= value or operator == "<=" and not core <= value or operator == ">" and not core > value or operator == "<" and not core < value or operator == "==" and not core == value:
            return False
    return True


class PluginType(str, Enum):
    AGENT = "agent"
    PROVIDER = "provider"
    SKILL = "skill"
    EXECUTOR = "executor"
    RUNTIME = "runtime"
    RESEARCH = "research"
    ASSET_SOURCE = "asset_source"
    QUALITY_GATE = "quality_gate"


class PluginPermission(str, Enum):
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    SHELL = "shell"
    SUBPROCESS = "subprocess"
    NETWORK = "network"
    SECRETS = "secrets"
    UI = "ui"


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    protocol: str
    plugin_type: PluginType
    platforms: FrozenSet[str]
    capabilities: FrozenSet[str]
    permissions: FrozenSet[PluginPermission]
    entrypoint: str
    rpc_methods: FrozenSet[str]

    @classmethod
    def parse(cls, value: Dict[str, Any]) -> "PluginManifest":
        plugin_id = str(value.get("id") or "")
        name = str(value.get("name") or "")
        version = str(value.get("version") or "")
        protocol = str(value.get("protocol") or value.get("protocol_version") or "")
        plugin_type_value = str(value.get("type") or "")
        entrypoint = str(value.get("entrypoint") or "adapter.py")
        rpc_methods = _strings(value.get("rpc_methods", []))
        allowed_methods = {"detect", "version", "auth", "health", "start", "send", "stream", "cancel", "usage", "quota"}
        if not rpc_methods or set(rpc_methods) - allowed_methods:
            raise ValueError("Plugin RPC methods are invalid.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", plugin_id):
            raise ValueError("Plugin id is invalid.")
        if not name or len(name) > 160 or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
            raise ValueError("Plugin name or semantic version is invalid.")
        negotiate_protocol(protocol)
        try:
            plugin_type = PluginType(plugin_type_value)
        except ValueError as exc:
            raise ValueError("Plugin type is invalid.") from exc
        platforms = _strings(value.get("platforms", []))
        if not platforms or set(platforms) - {"windows", "linux", "macos"}:
            raise ValueError("Plugin platforms are invalid.")
        capabilities = _strings(value.get("capabilities", []))
        if set(capabilities) - CAPABILITIES:
            raise ValueError("Plugin capabilities are invalid.")
        permission_values = _strings(value.get("permissions", []))
        try:
            permissions = frozenset(PluginPermission(item) for item in permission_values)
        except ValueError as exc:
            raise ValueError("Plugin permissions are invalid.") from exc
        if Path(entrypoint).is_absolute() or ".." in Path(entrypoint).parts or Path(entrypoint).suffix != ".py":
            raise ValueError("Plugin entrypoint must be a relative Python file path.")
        return cls(plugin_id, name, version, protocol, plugin_type, frozenset(platforms), frozenset(capabilities), permissions, entrypoint, frozenset(rpc_methods))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.plugin_id, "name": self.name, "version": self.version,
            "protocol": self.protocol, "type": self.plugin_type.value,
            "platforms": sorted(self.platforms), "capabilities": sorted(self.capabilities),
            "permissions": sorted(item.value for item in self.permissions), "entrypoint": self.entrypoint,
            "rpc_methods": sorted(self.rpc_methods),
        }


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Plugin manifest arrays must contain strings.")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))
