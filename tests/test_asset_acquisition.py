import unittest

from core.ai_fleet.services.asset_acquisition import AssetAcquisitionPolicy


class AssetAcquisitionPolicyTests(unittest.TestCase):
    def test_order_is_project_then_library_then_source_then_generation(self):
        policy = AssetAcquisitionPolicy()
        project = policy.plan([{"id": "p", "state": "ready", "license_approved": True}], [{"id": "l", "state": "ready", "license_approved": True}], [], True)
        library = policy.plan([], [{"id": "l", "state": "ready", "license_approved": True}], [], True)
        source = policy.plan([], [], [{"id": "s", "paid": False, "license_state": "approved"}], True)
        generated = policy.plan([], [], [], True)
        self.assertEqual([project["action"], library["action"], source["action"], generated["action"]], ["use_project_asset", "reuse_library_asset", "acquire_from_source", "generate_asset"])
        self.assertEqual(project["policy_order"], ["project", "library", "source", "generation"])

    def test_paid_or_unknown_license_is_blocked_for_approval(self):
        policy = AssetAcquisitionPolicy()
        for candidate in [{"id": "paid", "paid": True, "license_state": "approved"}, {"id": "unknown", "paid": False, "license_state": "unknown"}]:
            result = policy.plan([], [], [candidate], True)
            self.assertEqual(result["action"], "approval_required")
            self.assertTrue(result["approval_required"])


if __name__ == "__main__":
    unittest.main()
