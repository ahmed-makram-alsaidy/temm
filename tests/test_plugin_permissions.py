import unittest

from core.ai_fleet.plugin_permissions import PluginPermissionPolicy
from core.ai_fleet.plugin_protocol import PluginManifest


MANIFEST = {
    "id": "permission-agent", "name": "Permission Agent", "version": "1.0.0", "protocol": "1.0",
    "type": "agent", "platforms": ["windows"], "capabilities": ["coding"],
    "permissions": ["filesystem_read", "filesystem_write", "shell", "subprocess"], "entrypoint": "adapter.py", "rpc_methods": ["detect", "start", "send", "cancel"],
}


class PluginPermissionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PluginPermissionPolicy()
        self.manifest = PluginManifest.parse(MANIFEST)

    def test_developer_profile_allows_declared_development_permissions(self):
        operations = self.policy.enforce(self.manifest, "developer", MANIFEST["permissions"])
        self.assertEqual({item.value for item in operations}, {"file_read", "file_write", "shell", "subprocess"})

    def test_safe_profile_blocks_write_shell_and_subprocess(self):
        with self.assertRaises(PermissionError):
            self.policy.enforce(self.manifest, "safe", MANIFEST["permissions"])

    def test_missing_and_undeclared_grants_are_rejected(self):
        with self.assertRaises(PermissionError):
            self.policy.enforce(self.manifest, "developer", ["filesystem_read"])
        with self.assertRaises(PermissionError):
            self.policy.enforce(self.manifest, "full", [*MANIFEST["permissions"], "network"])

    def test_secret_and_ui_permissions_require_full_profile(self):
        manifest = PluginManifest.parse({**MANIFEST, "permissions": ["secrets", "ui"]})
        with self.assertRaises(PermissionError):
            self.policy.enforce(manifest, "developer", ["secrets", "ui"])
        self.policy.enforce(manifest, "full", ["secrets", "ui"])


if __name__ == "__main__":
    unittest.main()
