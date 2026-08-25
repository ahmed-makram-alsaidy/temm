import json
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.build_provenance import BuildProvenance
from core.ai_fleet.license_policy import LicensePolicy


class LicensePolicyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parents[1]

    def test_canonical_license_metadata_dependency_inventory_and_bundle_pass(self):
        result = LicensePolicy().verify(self.root)
        self.assertEqual(result["license"], "Apache-2.0")
        self.assertEqual(result["python_dependencies"], 30)
        self.assertEqual(result["frontend_runtime_dependencies"], 9)
        self.assertFalse(result["notice_required"])
        self.assertEqual((self.root / "LICENSE").read_bytes(), (self.root / "sdk" / "LICENSE").read_bytes())

    @unittest.skipUnless((Path(__file__).parents[1] / "apps" / "web" / "node_modules").is_dir(), "npm dependencies are required to regenerate exact upstream licenses")
    def test_frontend_bundle_is_deterministic_and_contains_exact_upstream_notices(self):
        service = LicensePolicy()
        path = service.generate_frontend_bundle(self.root)
        first = path.read_bytes()
        second = service.generate_frontend_bundle(self.root).read_bytes()
        self.assertEqual(first, second)
        text = first.decode()
        for marker in [
            "Copyright 2022 The Alexandria Project Authors",
            "Copyright 2019 The Manrope Project Authors",
            "Copyright (c) 2017-2019, The xterm.js authors",
            "Copyright (c) 2026 Lucide Icons and Contributors",
            "Copyright (c) Meta Platforms, Inc. and affiliates.",
        ]:
            self.assertIn(marker, text)

    def test_sbom_preserves_first_and_third_party_license_expressions(self):
        sbom = BuildProvenance().sbom(self.root)
        self.assertEqual(sbom["metadata"]["component"]["licenses"], [{"expression": "Apache-2.0"}])
        by_name = {item["name"]: item for item in sbom["components"]}
        self.assertEqual(by_name["certifi"]["licenses"], [{"expression": "MPL-2.0"}])
        self.assertEqual(by_name["cryptography"]["licenses"], [{"expression": "Apache-2.0 OR BSD-3-Clause"}])
        self.assertEqual(by_name["@fontsource-variable/alexandria"]["licenses"], [{"expression": "OFL-1.1"}])

    def test_installer_build_includes_license_and_dependency_inventory(self):
        text = (self.root / "tools" / "installer" / "build-windows-package.ps1").read_text(encoding="utf-8")
        self.assertIn("LICENSE dependency-licenses.json", text)
        self.assertIn("apps\\web\\dist", text)


if __name__ == "__main__":
    unittest.main()
