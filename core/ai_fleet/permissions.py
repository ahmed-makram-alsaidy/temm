from enum import Enum
from typing import Dict, FrozenSet, Iterable, Set


class Operation(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SHELL = "shell"
    NETWORK = "network"
    TOOL_CALLING = "tool_calling"
    GIT = "git"
    MODEL_SELECTION = "model_selection"
    INTERACTIVE = "interactive"
    SECRETS = "secrets"
    SUBPROCESS = "subprocess"
    UI = "ui"


PROFILE_GRANTS: Dict[str, FrozenSet[Operation]] = {
    "safe": frozenset({Operation.FILE_READ, Operation.INTERACTIVE}),
    "developer": frozenset({
        Operation.FILE_READ,
        Operation.FILE_WRITE,
        Operation.SHELL,
        Operation.TOOL_CALLING,
        Operation.GIT,
        Operation.MODEL_SELECTION,
        Operation.INTERACTIVE,
        Operation.SUBPROCESS,
    }),
    "full": frozenset(Operation),
}


CAPABILITY_OPERATIONS: Dict[str, Operation] = {
    "file_read": Operation.FILE_READ,
    "file_write": Operation.FILE_WRITE,
    "shell": Operation.SHELL,
    "network": Operation.NETWORK,
    "tool_calling": Operation.TOOL_CALLING,
    "git": Operation.GIT,
    "model_selection": Operation.MODEL_SELECTION,
    "interactive": Operation.INTERACTIVE,
    "pty": Operation.INTERACTIVE,
}


class PermissionPolicy:
    def validate_profile(self, profile: str) -> str:
        if profile not in PROFILE_GRANTS:
            raise ValueError(f"Unsupported permission profile: {profile}")
        return profile

    def required_operations(self, capabilities: Iterable[str]) -> Set[Operation]:
        return {CAPABILITY_OPERATIONS[item] for item in capabilities if item in CAPABILITY_OPERATIONS}

    def allows(self, profile: str, operations: Iterable[Operation]) -> bool:
        grants = PROFILE_GRANTS[self.validate_profile(profile)]
        return set(operations) <= grants

    def missing(self, profile: str, operations: Iterable[Operation]) -> Set[Operation]:
        grants = PROFILE_GRANTS[self.validate_profile(profile)]
        return set(operations) - grants

    def enforce_agent_workspace(self, agent_profile: str, workspace_profile: str, capabilities: Iterable[str]) -> None:
        required = self.required_operations(capabilities)
        missing_agent = self.missing(agent_profile, required)
        missing_workspace = self.missing(workspace_profile, required)
        missing = missing_agent | missing_workspace
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise PermissionError(f"Permission profile does not allow: {names}")


permission_policy = PermissionPolicy()
