import json
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.build_provenance import BuildProvenance


class BuildProvenanceTests(unittest.TestCase):
    def test_manifest_is_deterministic_and_constraints_truthful(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "b.txt").write_text("b")
            (root / "a.txt").write_text("a")
            one = BuildProvenance().manifest(root, ["b.txt", "a.txt"], {"python": "3.12"})
            two = BuildProvenance().manifest(root, ["a.txt", "b.txt"], {"python": "3.12"})
        self.assertEqual(one, two)
        self.assertEqual([item["path"] for item in one["files"]], ["a.txt", "b.txt"])
        self.assertFalse(one["python_dependencies_locked"])
        self.assertFalse(one["frontend_dependencies_locked"])

    def test_release_evidence_is_byte_reproducible(self):
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first"
            second = Path(folder) / "second"
            service = BuildProvenance()
            one = service.generate(root, first, {"python": "3.12", "platform": "test"})
            two = service.generate(root, second, {"python": "3.12", "platform": "test"})
            self.assertEqual(one, two)
            for name in one["files"]:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            provenance = json.loads((first / "build-provenance.json").read_text())
            sbom = json.loads((first / "sbom.cdx.json").read_text())
        self.assertTrue(provenance["python_dependencies_locked"])
        self.assertTrue(provenance["frontend_dependencies_locked"])
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertGreater(len(sbom["components"]), 30)

    def test_lock_entries_require_versions_and_sha256(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "requirements-lock.txt"
            lock.write_text("example>=1\n")
            with self.assertRaisesRegex(ValueError, "Invalid lock entry"):
                BuildProvenance().python_components(lock)


if __name__ == "__main__":
    unittest.main()
