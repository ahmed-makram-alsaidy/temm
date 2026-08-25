from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet


DOMAIN_SCHEMA_VERSION = "1.0"
CAPABILITY_SCHEMA_VERSION = "1.0"
STATE_SCHEMA_VERSION = "1.0"


class DomainKind(str, Enum):
    PROJECT = "project"
    WORKSPACE = "workspace"
    AGENT = "agent"
    RUNTIME = "runtime"
    MODEL = "model"
    PROVIDER = "provider"
    SKILL = "skill"
    ASSET = "asset"
    REQUIREMENT = "requirement"
    TASK = "task"
    RUN = "run"
    DELIVERABLE = "deliverable"


@dataclass(frozen=True)
class DomainDefinition:
    kind: DomainKind
    responsibility: str
    identity_scope: str
    may_execute: bool = False


DOMAIN_DEFINITIONS: Dict[DomainKind, DomainDefinition] = {
    DomainKind.PROJECT: DomainDefinition(DomainKind.PROJECT, "Persistent product outcome, truth, plan, and delivery scope.", "global"),
    DomainKind.WORKSPACE: DomainDefinition(DomainKind.WORKSPACE, "Approved filesystem boundary attached to projects or runs.", "global"),
    DomainKind.AGENT: DomainDefinition(DomainKind.AGENT, "Executable tool using capabilities, runtimes, models, and permissions.", "global", True),
    DomainKind.RUNTIME: DomainDefinition(DomainKind.RUNTIME, "Execution environment or local model host; not an Agent or Model.", "global", True),
    DomainKind.MODEL: DomainDefinition(DomainKind.MODEL, "AI model identity and evidence; never an executable Agent.", "provider_or_runtime"),
    DomainKind.PROVIDER: DomainDefinition(DomainKind.PROVIDER, "Configured service instance exposing model and execution capabilities.", "global", True),
    DomainKind.SKILL: DomainDefinition(DomainKind.SKILL, "Reusable capability requirement and instruction/tool recipe, independent of Model.", "global"),
    DomainKind.ASSET: DomainDefinition(DomainKind.ASSET, "Versioned project or library file with type, provenance, license, and usage.", "project_or_library"),
    DomainKind.REQUIREMENT: DomainDefinition(DomainKind.REQUIREMENT, "Versioned statement of needed behavior, constraint, quality, or production outcome.", "project"),
    DomainKind.TASK: DomainDefinition(DomainKind.TASK, "Executable unit of planned work linked to requirements and acceptance criteria.", "project"),
    DomainKind.RUN: DomainDefinition(DomainKind.RUN, "Immutable evidence-bearing execution lifecycle containing one or more attempts.", "project_or_standalone"),
    DomainKind.DELIVERABLE: DomainDefinition(DomainKind.DELIVERABLE, "Packaged output traced to requirements, assets, runs, and quality evidence.", "project"),
}


class Capability(str, Enum):
    TEXT_GENERATION = "text_generation"
    INTERACTIVE = "interactive"
    PTY = "pty"
    STDIN = "stdin"
    STREAMING = "streaming"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    MULTI_FILE_EDIT = "multi_file_edit"
    DEPENDENCY_MANAGEMENT = "dependency_management"
    COMMAND_EXECUTION = "command_execution"
    DEBUGGING = "debugging"
    PROJECT_REFACTOR = "project_refactor"
    SHELL = "shell"
    TOOL_CALLING = "tool_calling"
    MODEL_SELECTION = "model_selection"
    IMAGE_INPUT = "image_input"
    CODING = "coding"
    REASONING = "reasoning"
    RESEARCH = "research"
    GENERAL = "general"
    OFFLINE = "offline"
    GIT = "git"
    MULTIMODAL = "multimodal"
    FAST = "fast"
    NETWORK = "network"
    ASSET_SEARCH = "asset_search"
    ASSET_TRANSFORM = "asset_transform"
    QUALITY_GATE = "quality_gate"


CAPABILITIES: FrozenSet[str] = frozenset(item.value for item in Capability)


class EvidenceState(str, Enum):
    VERIFIED = "verified"
    DETECTED = "detected"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    BROKEN = "broken"
    NOT_AVAILABLE = "not_available"


class LifecycleState(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ExecutionState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    TERMINATING = "terminating"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"


class MeasurementProvenance(str, Enum):
    MEASURED = "measured"
    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


def validate_capabilities(values: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(values))
    unknown = set(normalized) - CAPABILITIES
    if unknown:
        raise ValueError(f"Unsupported capabilities: {sorted(unknown)}")
    return normalized
