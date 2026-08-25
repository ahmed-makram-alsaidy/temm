"""TEMM-owned execution profile for the OpenCode CLI executor.

TEMM used to dispatch production work into `--agent coder`, an agent profile
authored outside TEMM in the operator's own OpenCode configuration. That profile
carries a model, a temperature, a permission set and - decisively - a `steps`
budget, none of which TEMM declared, versioned, or could inspect. Production
evidence collected 2026-08-19 shows what that costs: `run-e757ad4b3b51` spent
560 seconds and exactly 50 agentic steps reading 175 files, hit the operator
profile's `steps: 50` ceiling, was forced into a text-only response before it
wrote a single line, and exited 0. TEMM read that as a clean completion with no
effect and blamed the route. The executor was never incapable and never
disobedient; it was cut off by a budget TEMM did not know existed.

So TEMM declares its own executor profile here and points the CLI at it through
`OPENCODE_CONFIG`. The profile lives under TEMM's state directory rather than in
the target workspace: a config file written into the project under work would be
picked up by workspace snapshots and ship inside the deliverable, so the one
place it must not go is the directory whose diff TEMM measures.

Declaring the agent, however, is only half of what the executor needs. The CLI
resolves *providers* by walking up from its working directory, and TEMM
deliberately runs it in an isolated temporary workspace with no such ancestry.
Production evidence 2026-08-20: `run-133922d95108` probed an
`agentrouter-openai` route declared in the repository's own `opencode.json`. From
the repository the CLI resolves 341 models; from the tournament's temporary
workspace it resolves 338, the missing three being exactly that provider's. The
attempt exited 1 in 1.9 seconds having never reached the provider, and TEMM
recorded the route as unable to write files. The route was never measured.

`OPENCODE_CONFIG` therefore has to carry the provider declarations too. It merges
with - rather than replaces - the operator's global configuration, and it accepts
a single path, so propagation means merging the *non-secret* provider
declarations discovered around the executable's own environment into the profile
TEMM generates. Credentials are never copied: only the CLI's own `{env:...}` and
`{file:...}` indirections survive sanitisation, so the key itself stays in the
child environment where it always lived, and a provider block holding a literal
secret is dropped whole rather than written to disk. Nothing here knows any
provider by name; it propagates whatever configuration the discovered executable
would itself have honoured.
"""

import json
import os
import re
from pathlib import Path


TEMM_EXECUTOR_AGENT = "temm-executor"
DEFAULT_EXECUTOR_STEP_BUDGET = 400
# The operator profile allowed 50. A production implementation task legitimately
# reads a codebase, writes several files, and runs a test suite, and the observed
# rate is roughly three tool calls per step, so 50 steps buys about 150 tool
# calls - less than one exhausted attempt actually consumed on reading alone. The
# wall-clock timeout is the bound TEMM sets deliberately per task and can account
# for; the step budget should not silently pre-empt it.
MIN_EXECUTOR_STEP_BUDGET = 20
MAX_EXECUTOR_STEP_BUDGET = 5000

EXECUTOR_SYSTEM_PROMPT = """You are TEMM's production executor.

The instruction you receive names the exact files your work is measured on. Read
only what you need to write them correctly, then write them. An investigation
that ends without those files on disk is a failed run, however well reasoned.

Stay inside the working directory you were started in. Do not look for the task
definition elsewhere on the filesystem - the instruction you were given is the
whole contract, and any other copy of it you find is stale."""

# Config file names the CLI itself recognises in a directory, nearest name first.
PROVIDER_CONFIG_FILENAMES = ("opencode.jsonc", "opencode.json")
# Ancestor directories to inspect. Deep enough for any real checkout, bounded so
# a pathological path cannot turn discovery into an unbounded filesystem walk.
MAX_PROVIDER_CONFIG_DEPTH = 24
# Fields whose value is a credential rather than a description of a provider. The
# match is on the field name because that is the only brand-independent signal
# available - the point is to propagate configuration without ever propagating a
# key, for whichever provider the operator happens to have declared.
CREDENTIAL_KEY = re.compile(
    r"(?i)(api[-_]?key|access[-_]?key|secret|token|password|passwd|authorization|credential|bearer)"
)
# The CLI's own indirections. These are safe to copy precisely because they are
# not the secret: they name where the child process should look for it.
CONFIG_REFERENCE = re.compile(r"^\{(?:env|file):[^{}]+\}$")
ENV_REFERENCE = re.compile(r"^\{env:([^{}]+)\}$")
# Below this length a coincidental substring match is likelier than a real leak,
# and flagging it would drop working provider configuration for nothing.
MIN_SECRET_LENGTH = 12
# The mark editors leave on Windows. The repository config this exists to
# propagate carries one, and `json.loads` rejects it outright.
BYTE_ORDER_MARK = "﻿"

_DROP = object()


def executor_step_budget() -> int:
    """Return the bounded agentic-step budget granted to the CLI executor."""
    raw = os.environ.get("TEMM_EXECUTOR_STEP_BUDGET", str(DEFAULT_EXECUTOR_STEP_BUDGET))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_EXECUTOR_STEP_BUDGET
    return max(MIN_EXECUTOR_STEP_BUDGET, min(value, MAX_EXECUTOR_STEP_BUDGET))


def _normalize_jsonc(text: str) -> str:
    """Strip the comments and trailing commas the CLI tolerates but `json` does not.

    Scanned rather than regexed because provider configuration legitimately holds
    URLs, and `https://host` contains the line-comment marker. A config the
    operator's own CLI reads must not become invisible to TEMM over punctuation.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        if char in "}]":
            while out and out[-1].isspace():
                out.pop()
            if out and out[-1] == ",":
                out.pop()
        out.append(char)
        index += 1
    return "".join(out)


def decode_config_document(text: str) -> dict | None:
    """Parse a CLI configuration document, or return None if it is not one."""
    try:
        document = json.loads(_normalize_jsonc(text.lstrip(BYTE_ORDER_MARK)))
    except (json.JSONDecodeError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _path_key(path: Path) -> str:
    """Return a comparable identity for a path, case-folded where the OS folds."""
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(path)))


def profile_root() -> Path:
    """Return the TEMM-owned directory holding the executor profile."""
    return Path(os.environ.get("TEMM_STATE_DIR", str(Path.home() / ".ai_fleet"))) / "executor"


def _operator_config_keys() -> set[str]:
    """Identify the configuration that is never propagated.

    The operator's global config is already merged by the CLI itself, so copying
    it would be redundant - and it is the one config TEMM has no mandate over: it
    may hold literal keys the operator chose to keep there, and TEMM must not
    relocate them. TEMM's own generated profile is excluded so a rewrite cannot
    read back what the previous dispatch wrote.
    """
    roots: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        roots.append(Path(xdg) / "opencode")
    roots.append(Path.home() / ".config" / "opencode")
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "opencode")
    keys = {_path_key(profile_root() / "opencode.json")}
    for root in roots:
        for name in PROVIDER_CONFIG_FILENAMES:
            keys.add(_path_key(root / name))
    return keys


def provider_config_search_root() -> Path:
    """Return the directory whose provider configuration the executor inherits.

    Defaults to TEMM's own working directory - the environment the executable was
    discovered in, and so the configuration the operator meant it to run under.
    """
    return Path(os.environ.get("TEMM_PROVIDER_CONFIG_ROOT") or os.getcwd())


def _candidate_config_paths(root: Path) -> list[Path]:
    """List the configs the CLI would have found by walking up from `root`."""
    directories: list[Path] = []
    directory = root
    for _ in range(MAX_PROVIDER_CONFIG_DEPTH):
        directories.append(directory)
        if directory.parent == directory:
            break
        directory = directory.parent
    excluded = _operator_config_keys()
    paths: list[Path] = []
    for directory in directories:
        for name in PROVIDER_CONFIG_FILENAMES:
            candidate = directory / name
            if _path_key(candidate) in excluded:
                continue
            try:
                if candidate.is_file():
                    paths.append(candidate)
            except OSError:
                continue
    return paths


def sanitize_provider_block(block: dict) -> tuple[dict, list[str], list[str]]:
    """Copy a provider declaration without its credentials.

    Returns the safe copy, the environment variables it defers to, and the field
    names dropped for holding a literal value. A dropped field is reported by
    name only: what it contained is exactly what must not be recorded.
    """
    env_vars: list[str] = []
    dropped: list[str] = []

    def walk(node, field: str | None = None):
        if isinstance(node, dict):
            clean = {}
            for key, value in node.items():
                child = walk(value, key)
                if child is _DROP:
                    dropped.append(str(key))
                    continue
                clean[key] = child
            return clean
        if isinstance(node, list):
            return [item for item in (walk(entry, field) for entry in node) if item is not _DROP]
        if isinstance(node, str) and field and CREDENTIAL_KEY.search(str(field)):
            candidate = node.strip()
            match = ENV_REFERENCE.match(candidate)
            if match:
                name = match.group(1).strip()
                if name:
                    env_vars.append(name)
                return node
            if CONFIG_REFERENCE.match(candidate):
                return node
            return _DROP
        return node

    return walk(block), env_vars, dropped


def _leaked_secret_names(block: dict) -> list[str]:
    """Name environment secrets whose literal value appears inside a block.

    A backstop for a credential written under a field name no rule anticipates.
    Only the variable name is returned, and the block is discarded rather than
    sanitised further: a leak found here means the shape of that configuration is
    not understood well enough to edit it safely.
    """
    try:
        blob = json.dumps(block)
    except (TypeError, ValueError):
        return []
    leaked: list[str] = []
    for name, value in os.environ.items():
        if not value or len(value) < MIN_SECRET_LENGTH:
            continue
        if not CREDENTIAL_KEY.search(name):
            continue
        if value in blob:
            leaked.append(name)
    return leaked


def discover_provider_config(root: Path | None = None) -> dict:
    """Collect the provider declarations an isolated executor would otherwise lose.

    Nearest configuration wins, matching how the CLI resolves it: a checkout that
    overrides a provider its parent directory declares keeps the override.
    """
    search_root = Path(root) if root is not None else provider_config_search_root()
    providers: dict = {}
    sources: list[str] = []
    env_vars: list[str] = []
    dropped: list[dict] = []
    for path in _candidate_config_paths(search_root):
        try:
            document = decode_config_document(path.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
        if not document:
            continue
        declared = document.get("provider")
        if not isinstance(declared, dict):
            continue
        contributed = False
        for provider_id, block in declared.items():
            if provider_id in providers or not isinstance(block, dict):
                continue
            clean, referenced, removed = sanitize_provider_block(block)
            leaked = _leaked_secret_names(clean)
            if leaked:
                dropped.append({"provider": provider_id, "field": "*", "credential_env_vars": sorted(leaked)})
                continue
            providers[provider_id] = clean
            contributed = True
            for name in referenced:
                if name not in env_vars:
                    env_vars.append(name)
            for field in removed:
                dropped.append({"provider": provider_id, "field": field})
        if contributed:
            sources.append(str(path))
    return {
        "providers": providers,
        "sources": sources,
        "provider_ids": sorted(providers),
        # Presence, never the value: the executor needs the variable set, and
        # TEMM needs to be able to say which one was missing when it was not.
        "credential_env_vars": [{"name": name, "present": bool(os.environ.get(name))} for name in env_vars],
        "dropped_literal_credentials": dropped,
        "search_root": str(search_root),
    }


def credential_env_presence(providers: dict) -> list[dict]:
    """Report the environment variables a set of provider blocks defers to.

    Presence only. Which variable a provider needs is configuration TEMM must be
    able to explain a failure with; what the variable holds is not.
    """
    names: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            match = ENV_REFERENCE.match(node.strip())
            if match:
                name = match.group(1).strip()
                if name and name not in names:
                    names.append(name)

    walk(providers or {})
    return [{"name": name, "present": bool(os.environ.get(name))} for name in names]


def propagation_summary(propagation: dict) -> dict:
    """Reduce a propagation result to what an attempt receipt should carry."""
    return {
        "provider_ids": list(propagation.get("provider_ids") or []),
        "sources": list(propagation.get("sources") or []),
        "credential_env_vars": list(propagation.get("credential_env_vars") or []),
        "dropped_literal_credentials": list(propagation.get("dropped_literal_credentials") or []),
        "search_root": propagation.get("search_root"),
    }


def profile_document(step_budget: int | None = None, providers: dict | None = None) -> dict:
    """Build the OpenCode configuration document TEMM dispatches under."""
    document = {
        "$schema": "https://opencode.ai/config.json",
        "agent": {
            TEMM_EXECUTOR_AGENT: {
                "description": "TEMM production executor: direct file operations under a declared step budget.",
                "mode": "all",
                "steps": executor_step_budget() if step_budget is None else step_budget,
                "prompt": EXECUTOR_SYSTEM_PROMPT,
                "permission": {
                    "read": "allow",
                    "edit": "allow",
                    "bash": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "list": "allow",
                    # Sub-delegation splits one measured attempt into children TEMM
                    # cannot attribute a diff to, and each child spends the same
                    # budget the parent is judged on.
                    "task": "deny",
                },
            }
        },
    }
    if providers:
        document["provider"] = providers
    return document


def prepare_profile(
    root: Path | None = None,
    step_budget: int | None = None,
    provider_config_root: Path | None = None,
) -> tuple[Path, dict]:
    """Materialize the profile and report what provider configuration it carries.

    Written on every dispatch rather than once at install time: the step budget is
    read from the environment and the provider set is read from disk, and a
    profile that silently lagged either would reintroduce exactly the invisible
    ceiling and the missing provider this module exists to remove.
    """
    propagation = discover_provider_config(provider_config_root)
    directory = root or profile_root()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "opencode.json"
    document = profile_document(step_budget, propagation["providers"])
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path, propagation


def write_profile(root: Path | None = None, step_budget: int | None = None) -> Path:
    """Materialize the profile and return its path."""
    return prepare_profile(root, step_budget)[0]


def child_env(root: Path | None = None, step_budget: int | None = None) -> dict:
    """Return the environment overlay that binds the CLI to TEMM's profile.

    `OPENCODE_CONFIG` is merged over the operator's global configuration, so the
    profile need only declare what TEMM adds - and it accepts a single path, which
    is why the propagated providers are merged into this one document rather than
    appended as a second config.
    """
    return {"OPENCODE_CONFIG": str(write_profile(root, step_budget))}


def executor_config(
    root: Path | None = None,
    step_budget: int | None = None,
    provider_config_root: Path | None = None,
) -> tuple[dict, dict]:
    """Return the environment overlay and the propagation record for a receipt."""
    path, propagation = prepare_profile(root, step_budget, provider_config_root)
    return {"OPENCODE_CONFIG": str(path)}, propagation_summary(propagation)
