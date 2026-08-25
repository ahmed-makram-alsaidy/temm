import unittest
from pathlib import Path


class SecurityPolicyTests(unittest.TestCase):
    def test_policy_states_reporting_blocker_response_and_boundaries(self):
        text = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("GitHub Private Vulnerability Reporting", text)
        self.assertIn("not yet active", text)
        self.assertNotIn("security@example", text)
        for term in ["within 7 days", "within 14 days", "Coordinated disclosure", "Workspaces", "CLI/PTY", "provider/network", "out-of-process plugins", "Downloads", "Secrets"]:
            self.assertIn(term, text)

    def test_policy_covers_current_plugin_download_media_and_incident_controls(self):
        text = Path("SECURITY.md").read_text(encoding="utf-8")
        for term in ["signed-catalog", "extracted-folder hashes", "scoped approvals", "not a complete operating-system sandbox", "Media transforms", "atomic outputs", "regression tests", "Rotate any credential"]:
            self.assertIn(term, text)

    def test_threat_model_no_longer_claims_completed_foundations_are_absent(self):
        text = Path("docs/SECURITY_THREAT_MODEL.md").read_text(encoding="utf-8")
        for stale in ["CORS permits all origins", "Research engine not operational", "No autonomous downloader", "Database evolution uses inline"]:
            self.assertNotIn(stale, text)
        for implemented in ["checksummed migrations", "out-of-process RPC", "bounded FFmpeg transforms", "scoped approvals", "persistent sequences"]:
            self.assertIn(implemented, text)


if __name__ == "__main__":
    unittest.main()
