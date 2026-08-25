import unittest

from core.ai_fleet.permissions import Operation, PermissionPolicy


class PermissionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PermissionPolicy()

    def test_safe_profile_blocks_write_shell_network_and_tools(self):
        self.assertTrue(self.policy.allows("safe", {Operation.FILE_READ}))
        self.assertFalse(self.policy.allows("safe", {Operation.FILE_WRITE}))
        self.assertFalse(self.policy.allows("safe", {Operation.SHELL}))
        self.assertFalse(self.policy.allows("safe", {Operation.NETWORK}))
        self.assertFalse(self.policy.allows("safe", {Operation.TOOL_CALLING}))

    def test_developer_allows_development_but_not_network(self):
        operations = {Operation.FILE_READ, Operation.FILE_WRITE, Operation.SHELL, Operation.GIT, Operation.TOOL_CALLING}
        self.assertTrue(self.policy.allows("developer", operations))
        self.assertFalse(self.policy.allows("developer", {Operation.NETWORK}))

    def test_full_allows_every_operation(self):
        self.assertTrue(self.policy.allows("full", set(Operation)))

    def test_capabilities_map_to_required_operations(self):
        required = self.policy.required_operations(["coding", "file_write", "shell", "pty"])
        self.assertEqual(required, {Operation.FILE_WRITE, Operation.SHELL, Operation.INTERACTIVE})

    def test_agent_and_workspace_must_both_allow_operations(self):
        with self.assertRaises(PermissionError):
            self.policy.enforce_agent_workspace("developer", "safe", ["file_write", "shell"])
        with self.assertRaises(PermissionError):
            self.policy.enforce_agent_workspace("safe", "developer", ["file_write"])
        self.policy.enforce_agent_workspace("developer", "developer", ["file_write", "shell"])

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            self.policy.validate_profile("custom")


if __name__ == "__main__":
    unittest.main()
