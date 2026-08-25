from typing import Iterable, Set

from .permissions import Operation, permission_policy
from .plugin_protocol import PluginManifest, PluginPermission


PERMISSION_OPERATIONS = {
    PluginPermission.FILESYSTEM_READ: Operation.FILE_READ,
    PluginPermission.FILESYSTEM_WRITE: Operation.FILE_WRITE,
    PluginPermission.SHELL: Operation.SHELL,
    PluginPermission.SUBPROCESS: Operation.SUBPROCESS,
    PluginPermission.NETWORK: Operation.NETWORK,
    PluginPermission.SECRETS: Operation.SECRETS,
    PluginPermission.UI: Operation.UI,
}


class PluginPermissionPolicy:
    def operations(self, permissions: Iterable[PluginPermission]) -> Set[Operation]:
        return {PERMISSION_OPERATIONS[item] for item in permissions}

    def enforce(self, manifest: PluginManifest, profile: str, granted_permissions: Iterable[str]) -> Set[Operation]:
        try:
            granted = {PluginPermission(item) for item in granted_permissions}
        except ValueError as exc:
            raise PermissionError("Unknown plugin permission grant.") from exc
        undeclared = granted - manifest.permissions
        missing = manifest.permissions - granted
        if undeclared:
            raise PermissionError("Plugin grant contains undeclared permissions.")
        if missing:
            raise PermissionError("All requested plugin permissions must be explicitly granted.")
        operations = self.operations(granted)
        if not permission_policy.allows(profile, operations):
            denied = permission_policy.missing(profile, operations)
            raise PermissionError(f"Permission profile does not allow: {', '.join(sorted(item.value for item in denied))}")
        return operations


plugin_permission_policy = PluginPermissionPolicy()
