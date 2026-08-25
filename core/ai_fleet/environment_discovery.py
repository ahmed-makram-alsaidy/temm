"""External AI Environment Discovery for AI Fleet OS.

Inspects installed AI tools (OpenCode, Antigravity, etc.) and discovers their
configured providers, models, and authentication state without extracting secrets.

Produces evidence-linked records for:
- ExternalTool (installed CLI/application)
- ConfiguredProvider (provider instance behind a tool)
- DiscoveredModel (model available through a provider)
"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ExternalToolRecord:
    tool_id: str
    name: str
    executable_path: str
    version: str
    auth_state: str  # "verified" | "unverified" | "unknown"
    capabilities: List[str]
    discovered_at: str
    evidence_source: str


@dataclass
class ConfiguredProviderRecord:
    provider_id: str
    display_name: str
    protocol: str  # "openai_compatible" | "bedrock_converse" | "anthropic" | "custom"
    base_url: Optional[str]
    auth_type: str  # "api_key" | "oauth" | "bearer_token" | "env_var"
    auth_reference: str  # e.g. "opencode_credential:nvidia" or "env:AWS_BEARER_TOKEN_BEDROCK"
    source_tool: str  # tool_id of the tool that exposes this provider
    model_count: int
    discovered_at: str
    verified: bool


@dataclass
class DiscoveredModelRecord:
    model_id: str
    provider_id: str
    display_name: str
    source_tool: str
    discovered_at: str
    verified: bool = False


@dataclass
class EnvironmentInventory:
    tools: List[ExternalToolRecord] = field(default_factory=list)
    providers: List[ConfiguredProviderRecord] = field(default_factory=list)
    models: List[DiscoveredModelRecord] = field(default_factory=list)
    execution_probes: List[Dict[str, Any]] = field(default_factory=list)
    discovered_at: str = ""

    def summary(self) -> Dict[str, Any]:
        verified_providers = [p for p in self.providers if p.verified]
        verified_models = [m for m in self.models if m.verified]
        verified_routes = [p for p in self.execution_probes if p.get("success")]
        return {
            "tools_discovered": len(self.tools),
            "providers_configured": len(self.providers),
            "providers_verified": len(verified_providers),
            "models_catalogued": len(self.models),
            "models_verified": len(verified_models),
            "execution_routes_verified": len(verified_routes),
            "discovered_at": self.discovered_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "tools": [t.__dict__ for t in self.tools],
            "providers": [p.__dict__ for p in self.providers],
            "models_by_provider": self._models_by_provider(),
            "execution_probes": self.execution_probes,
        }

    def _models_by_provider(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for m in self.models:
            result.setdefault(m.provider_id, []).append(m.model_id)
        return result


def _run_command(args: List[str], timeout: float = 15.0, cwd: Optional[str] = None) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip()
        # Some CLIs output to stderr but still succeed
        if result.returncode == 0:
            return ""
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _discover_opencode() -> Optional[ExternalToolRecord]:
    """Discover OpenCode CLI installation."""
    import shutil
    path = shutil.which("opencode")
    if not path:
        return None
    version = _run_command([path, "--version"])
    if not version:
        return None
    # Check auth state via providers list (output goes to stderr with ANSI)
    try:
        result = subprocess.run(
            [path, "providers", "list"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        auth_state = "verified" if "credentials" in combined else "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        auth_state = "unknown"
    return ExternalToolRecord(
        tool_id="opencode-cli",
        name="OpenCode",
        executable_path=str(Path(path).resolve()),
        version=version.strip(),
        auth_state=auth_state,
        capabilities=["general", "coding", "shell", "file_read", "file_write", "streaming", "tool_calling", "model_selection"],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        evidence_source="system_scan",
    )


def _discover_antigravity() -> Optional[ExternalToolRecord]:
    """Discover Antigravity (agy) CLI installation."""
    import shutil
    path = shutil.which("agy")
    if not path:
        return None
    version = _run_command([path, "--version"])
    if not version:
        return None
    # Check auth by listing models
    models_output = _run_command([path, "models"], timeout=10)
    auth_state = "verified" if models_output and "gemini" in models_output.lower() else "unknown"
    return ExternalToolRecord(
        tool_id="antigravity-cli",
        name="Antigravity",
        executable_path=str(Path(path).resolve()),
        version=version.strip(),
        auth_state=auth_state,
        capabilities=["general", "coding", "shell", "file_read", "file_write", "streaming", "tool_calling", "model_selection"],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        evidence_source="system_scan",
    )


def _discover_claude() -> Optional[ExternalToolRecord]:
    """Discover Claude Code CLI installation."""
    import shutil
    path = shutil.which("claude")
    if not path:
        return None
    version = _run_command([path, "--version"])
    if not version:
        return None
    auth_output = _run_command([path, "auth", "status"], timeout=10)
    auth_state = "unknown"
    if auth_output:
        try:
            auth_data = json.loads(auth_output)
            auth_state = "verified" if auth_data.get("loggedIn") else "unverified"
        except json.JSONDecodeError:
            pass
    return ExternalToolRecord(
        tool_id="claude-code",
        name="Claude Code",
        executable_path=str(Path(path).resolve()),
        version=version.strip(),
        auth_state=auth_state,
        capabilities=["coding", "shell", "file_read", "file_write", "streaming", "tool_calling"],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        evidence_source="system_scan",
    )


def _discover_codex() -> Optional[ExternalToolRecord]:
    """Discover OpenAI Codex CLI installation."""
    import shutil
    path = shutil.which("codex")
    if not path:
        return None
    version = _run_command([path, "--version"])
    if not version:
        return None
    return ExternalToolRecord(
        tool_id="codex-cli",
        name="OpenAI Codex CLI",
        executable_path=str(Path(path).resolve()),
        version=version.strip(),
        auth_state="unknown",  # Cannot easily probe without making API call
        capabilities=["coding", "shell", "file_read", "file_write", "streaming", "tool_calling"],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        evidence_source="system_scan",
    )


def _discover_opencode_providers() -> tuple[List[ConfiguredProviderRecord], List[DiscoveredModelRecord]]:
    """Discover providers and models configured in OpenCode."""
    import shutil
    path = shutil.which("opencode")
    if not path:
        return [], []

    # Get model list
    models_output = _run_command([path, "models"], timeout=30)
    if not models_output:
        return [], []

    now = datetime.now(timezone.utc).isoformat()
    providers: Dict[str, ConfiguredProviderRecord] = {}
    models: List[DiscoveredModelRecord] = []

    # Parse opencode models output: "provider/model-id" per line
    for line in models_output.strip().splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        parts = line.split("/", 1)
        provider_id = parts[0]
        model_id = line  # full qualified ID

        if provider_id not in providers:
            # Determine protocol based on known provider types
            protocol = _infer_protocol(provider_id)
            auth_type = _infer_auth_type(provider_id)
            auth_ref = f"opencode_credential:{provider_id}"
            providers[provider_id] = ConfiguredProviderRecord(
                provider_id=f"opencode:{provider_id}",
                display_name=provider_id,
                protocol=protocol,
                base_url=None,  # Would need config inspection
                auth_type=auth_type,
                auth_reference=auth_ref,
                source_tool="opencode-cli",
                model_count=0,
                discovered_at=now,
                verified=False,
            )

        providers[provider_id].model_count += 1
        models.append(DiscoveredModelRecord(
            model_id=model_id,
            provider_id=f"opencode:{provider_id}",
            display_name=parts[1] if len(parts) > 1 else model_id,
            source_tool="opencode-cli",
            discovered_at=now,
        ))

    # Also read config for base URLs
    config_paths = [
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
        Path.home() / ".config" / "opencode" / "opencode.json",
    ]
    for config_path in config_paths:
        if config_path.exists():
            try:
                # Strip JSONC comments for parsing
                text = config_path.read_text(encoding="utf-8")
                # Simple comment stripping (single-line only)
                lines = [l for l in text.splitlines() if not l.strip().startswith("//")]
                data = json.loads("\n".join(lines))
                for pid, pconfig in (data.get("provider") or {}).items():
                    full_id = f"opencode:{pid}"
                    if full_id in {p.provider_id for p in providers.values()}:
                        for p in providers.values():
                            if p.provider_id == full_id:
                                options = pconfig.get("options") or {}
                                p.base_url = options.get("baseURL")
                                p.display_name = pconfig.get("name") or pid
                                break
            except (json.JSONDecodeError, OSError):
                pass
            break

    return list(providers.values()), models


def _discover_antigravity_models() -> List[DiscoveredModelRecord]:
    """Discover models available through Antigravity."""
    import shutil
    path = shutil.which("agy")
    if not path:
        return []
    output = _run_command([path, "models"], timeout=15)
    if not output:
        return []
    now = datetime.now(timezone.utc).isoformat()
    models = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("Fetching"):
            continue
        parts = line.split("\t")
        model_id = parts[0].strip() if parts else ""
        display_name = parts[1].strip() if len(parts) > 1 else model_id
        if model_id:
            models.append(DiscoveredModelRecord(
                model_id=f"antigravity/{model_id}",
                provider_id="antigravity:google",
                display_name=display_name,
                source_tool="antigravity-cli",
                discovered_at=now,
            ))
    return models


def _discover_bedrock_env() -> Optional[ConfiguredProviderRecord]:
    """Discover Bedrock from environment variable."""
    token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if not token:
        return None
    return ConfiguredProviderRecord(
        provider_id="env:bedrock",
        display_name="Amazon Bedrock (env)",
        protocol="bedrock_converse",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        auth_type="bearer_token",
        auth_reference="env:AWS_BEARER_TOKEN_BEDROCK",
        source_tool="environment",
        model_count=0,  # Will be updated during model discovery
        discovered_at=datetime.now(timezone.utc).isoformat(),
        verified=False,
    )


def _infer_protocol(provider_id: str) -> str:
    """Infer API protocol from provider identifier."""
    bedrock_ids = {"amazon-bedrock"}
    anthropic_ids = {"anthropic", "claude"}
    if provider_id in bedrock_ids:
        return "bedrock_converse"
    if provider_id in anthropic_ids:
        return "anthropic"
    # Most others (nvidia, aliyun, openai, groq, etc.) use OpenAI-compatible
    return "openai_compatible"


def _infer_auth_type(provider_id: str) -> str:
    """Infer auth type from provider identifier."""
    if provider_id == "openai":
        return "oauth"
    if provider_id == "amazon-bedrock":
        return "bearer_token"
    return "api_key"


def discover_environment() -> EnvironmentInventory:
    """Perform full external AI environment discovery."""
    inventory = EnvironmentInventory(discovered_at=datetime.now(timezone.utc).isoformat())

    # 1. Discover tools
    tool_discoverers = [
        _discover_opencode,
        _discover_antigravity,
        _discover_claude,
        _discover_codex,
    ]
    for discoverer in tool_discoverers:
        tool = discoverer()
        if tool:
            inventory.tools.append(tool)

    # 2. Discover providers and models from OpenCode
    oc_providers, oc_models = _discover_opencode_providers()
    inventory.providers.extend(oc_providers)
    inventory.models.extend(oc_models)

    # 3. Discover Antigravity models
    agy_models = _discover_antigravity_models()
    if agy_models:
        inventory.models.extend(agy_models)
        inventory.providers.append(ConfiguredProviderRecord(
            provider_id="antigravity:google",
            display_name="Google (via Antigravity)",
            protocol="custom",
            base_url=None,
            auth_type="oauth",
            auth_reference="antigravity_google_auth",
            source_tool="antigravity-cli",
            model_count=len(agy_models),
            discovered_at=datetime.now(timezone.utc).isoformat(),
            verified=False,
        ))

    # 4. Discover environment-based providers
    bedrock = _discover_bedrock_env()
    if bedrock:
        inventory.providers.append(bedrock)

    return inventory
