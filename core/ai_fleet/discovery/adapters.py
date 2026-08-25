import json
import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..domain import CAPABILITIES


class DiscoveryState(str, Enum):
    VERIFIED = "verified"
    DETECTED = "detected"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"
    BROKEN = "broken"


class ToolKind(str, Enum):
    AGENT = "agent"
    RUNTIME = "runtime"


ALLOWED_CAPABILITIES = CAPABILITIES


@dataclass(frozen=True)
class DiscoveryAdapter:
    adapter_id: str
    display_name: str
    kind: ToolKind
    executable_names: Sequence[str]
    version_args: Sequence[str]
    version_pattern: Optional[str]
    capabilities: Sequence[str]
    common_locations: Sequence[str]
    invocation_args: Sequence[str]
    input_method: str
    output_method: str
    working_directory: str
    timeout_seconds: float
    health_args: Sequence[str]
    auth_required: bool
    auth_method: str
    auth_setup_instructions: str
    auth_probe_args: Sequence[str]
    auth_probe_parser: Dict[str, Any]
    source: str

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any], source: str) -> "DiscoveryAdapter":
        adapter_id = str(manifest.get("id") or "").strip()
        display_name = str(manifest.get("name") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", adapter_id):
            raise ValueError(f"Invalid discovery adapter id in {source}.")
        if not display_name:
            raise ValueError(f"Discovery adapter {adapter_id} needs a name.")
        try:
            kind = ToolKind(str(manifest.get("kind") or "agent"))
        except ValueError as exc:
            raise ValueError(f"Discovery adapter {adapter_id} has an invalid kind.") from exc
        executable_names = _string_list(manifest.get("executables"))
        if not executable_names or any(Path(item).name != item for item in executable_names):
            raise ValueError(f"Discovery adapter {adapter_id} needs executable basenames.")
        version_args = validate_probe_args(manifest.get("version_probe", {}).get("args", []))
        health_args = validate_probe_args(manifest.get("health_probe", {}).get("args", []))
        auth_probe_args = validate_probe_args(manifest.get("auth", {}).get("probe", {}).get("args", []))
        auth_probe_parser = manifest.get("auth", {}).get("probe", {}).get("parser", {})
        if not isinstance(auth_probe_parser, dict):
            raise ValueError(f"Discovery adapter {adapter_id} has an invalid auth parser.")
        if auth_probe_parser.get("type") not in {None, "exit_zero", "output_regex", "json_field"}:
            raise ValueError(f"Discovery adapter {adapter_id} has an unsupported auth parser.")
        capabilities = _string_list(manifest.get("capabilities"))
        unknown = set(capabilities) - ALLOWED_CAPABILITIES
        if unknown:
            raise ValueError(f"Discovery adapter {adapter_id} has unknown capabilities: {sorted(unknown)}")
        timeout_seconds = float(manifest.get("version_probe", {}).get("timeout_seconds", 3.0))
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError(f"Discovery adapter {adapter_id} timeout must be between 0.1 and 30 seconds.")
        version_pattern = manifest.get("version_probe", {}).get("pattern")
        if version_pattern:
            re.compile(str(version_pattern))
        input_method = str(manifest.get("execution", {}).get("input_method", "argument"))
        output_method = str(manifest.get("execution", {}).get("output_method", "stdout"))
        working_directory = str(manifest.get("execution", {}).get("working_directory", "workspace"))
        if input_method not in {"argument", "stdin"}:
            raise ValueError(f"Discovery adapter {adapter_id} has an unsupported input method.")
        if output_method not in {"stdout", "json"}:
            raise ValueError(f"Discovery adapter {adapter_id} has an unsupported output method.")
        if working_directory not in {"workspace", "inherit"}:
            raise ValueError(f"Discovery adapter {adapter_id} has an unsupported working directory behavior.")
        return cls(
            adapter_id=adapter_id,
            display_name=display_name,
            kind=kind,
            executable_names=executable_names,
            version_args=version_args,
            version_pattern=str(version_pattern) if version_pattern else None,
            capabilities=capabilities,
            common_locations=_string_list(manifest.get("common_locations", {}).get(_platform_key(), [])),
            invocation_args=_string_list(manifest.get("execution", {}).get("args", [])),
            input_method=input_method,
            output_method=output_method,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
            health_args=health_args,
            auth_required=bool(manifest.get("auth", {}).get("required", False)),
            auth_method=str(manifest.get("auth", {}).get("method", "none")),
            auth_setup_instructions=str(manifest.get("auth", {}).get("setup_instructions", "")),
            auth_probe_args=auth_probe_args,
            auth_probe_parser=auth_probe_parser,
            source=source,
        )


class DiscoveryManifestLoader:
    def __init__(self, directories: Optional[Sequence[Path]] = None):
        builtin = Path(__file__).resolve().parent / "manifests"
        self._directories = list(directories or [builtin])

    def load(self) -> List[DiscoveryAdapter]:
        adapters: Dict[str, DiscoveryAdapter] = {}
        for directory in self._directories:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                manifests = payload if isinstance(payload, list) else [payload]
                for manifest in manifests:
                    adapter = DiscoveryAdapter.from_manifest(manifest, str(path))
                    if adapter.adapter_id in adapters:
                        raise ValueError(f"Duplicate discovery adapter id: {adapter.adapter_id}")
                    adapters[adapter.adapter_id] = adapter
        return list(adapters.values())


def validate_probe_args(value: Any) -> List[str]:
    args = _string_list(value)
    if len(args) > 16:
        raise ValueError("Probe arguments cannot exceed 16 items.")
    for item in args:
        if not item or len(item) > 256 or "\x00" in item or "\r" in item or "\n" in item:
            raise ValueError("Probe arguments contain an invalid value.")
    return args


def expand_location(value: str) -> Path:
    expanded = os.path.expandvars(value)
    return Path(expanded).expanduser()


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Manifest values must be string arrays.")
    return [item.strip() for item in value if item.strip()]


def _platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"
