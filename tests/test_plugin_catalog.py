import base64
import unittest
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.ai_fleet.plugin_catalog import CatalogError, CatalogSource, PluginCatalog


class PluginCatalogTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.service = PluginCatalog()
        self.source = CatalogSource("official-test", "https://plugins.example.test/catalog.json", base64.b64encode(public_key).decode(), True)
        now = datetime.now(timezone.utc)
        self.catalog = {
            "schema_version": "1.0",
            "source_id": "official-test",
            "generated_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "entries": [{
                "manifest": {
                    "id": "example-agent",
                    "name": "Example Agent",
                    "version": "1.2.3",
                    "protocol": "1.0",
                    "type": "agent",
                    "platforms": ["windows", "linux"],
                    "capabilities": ["coding", "shell"],
                    "permissions": ["filesystem_read", "shell"],
                    "entrypoint": "adapter.py",
                    "rpc_methods": ["detect", "health", "start", "cancel"],
                },
                "author": "Example Maintainer",
                "source_code_url": "https://code.example.test/example-agent",
                "package": {
                    "url": "https://plugins.example.test/example-agent-1.2.3.zip",
                    "sha256": "a" * 64,
                    "folder_sha256": "b" * 64,
                    "size": 4096,
                },
            }],
        }
        self.sign()

    def sign(self):
        signature = self.private_key.sign(self.service.canonical_payload(self.catalog))
        self.catalog["signature"] = base64.b64encode(signature).decode()

    def test_verified_catalog_still_requires_permission_review_and_install_action(self):
        result = self.service.verify(self.source, self.catalog, "windows")
        self.assertTrue(result["verified"])
        self.assertFalse(result["automatic_trust"])
        self.assertFalse(result["installation_enabled"])
        entry = result["entries"][0]
        self.assertTrue(entry["compatible"])
        self.assertTrue(entry["platform_supported"])
        self.assertTrue(entry["requires_permission_review"])
        self.assertEqual(entry["package"]["sha256"], "a" * 64)
        self.assertEqual(entry["package"]["folder_sha256"], "b" * 64)
        self.assertEqual(entry["reputation"], "unverified")
        self.assertTrue(entry["rollback"]["retain_previous_package"])

    def test_disabled_source_and_tampered_catalog_are_rejected(self):
        disabled = CatalogSource(self.source.source_id, self.source.index_url, self.source.public_key)
        with self.assertRaisesRegex(CatalogError, "not enabled"):
            self.service.verify(disabled, self.catalog, "windows")
        self.catalog["entries"][0]["author"] = "Tampered"
        with self.assertRaisesRegex(CatalogError, "signature"):
            self.service.verify(self.source, self.catalog, "windows")

    def test_expired_duplicate_and_invalid_package_are_rejected(self):
        self.catalog["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.sign()
        with self.assertRaisesRegex(CatalogError, "expired"):
            self.service.verify(self.source, self.catalog, "windows")
        self.catalog["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.catalog["entries"].append(dict(self.catalog["entries"][0]))
        self.sign()
        with self.assertRaisesRegex(CatalogError, "duplicate"):
            self.service.verify(self.source, self.catalog, "windows")
        self.catalog["entries"] = self.catalog["entries"][:1]
        self.catalog["entries"][0]["package"] = {**self.catalog["entries"][0]["package"], "sha256": "unknown"}
        self.sign()
        with self.assertRaisesRegex(CatalogError, "SHA-256"):
            self.service.verify(self.source, self.catalog, "windows")

    def test_signed_benchmark_pack_is_non_executable_and_versioned(self):
        pack = {"content_type": "benchmark_pack", "pack": {"id": "python-pack", "version": "1.2.0", "schema_version": "1.0", "category": "coding", "name": "Python Pack"}, "author": "Pack Author", "source_code_url": "https://code.example.test/python-pack", "package": {"url": "https://plugins.example.test/python-pack.json", "sha256": "c" * 64, "size": 1024, "media_type": "application/json"}}
        self.catalog["entries"] = [pack]
        self.sign()
        result = self.service.verify(self.source, self.catalog, "windows")
        entry = result["entries"][0]
        self.assertEqual(entry["content_type"], "benchmark_pack")
        self.assertFalse(entry["executable"])
        self.assertEqual(entry["permissions"], [])
        self.assertEqual(entry["identity"], {"id": "python-pack", "version": "1.2.0"})

    def test_signed_workflow_template_exposes_prerequisites_without_executable_claim(self):
        template = {"content_type": "workflow_template", "template": {"id": "review-flow", "version": "1.0.0", "schema_version": "1.0", "name": "Review Flow", "prerequisites": ["verified_agent"], "gate_ids": ["tests"]}, "author": "Flow Author", "source_code_url": "https://code.example.test/review-flow", "package": {"url": "https://plugins.example.test/review-flow.json", "sha256": "d" * 64, "size": 1024, "media_type": "application/json"}}
        self.catalog["entries"] = [template]
        self.sign()
        entry = self.service.verify(self.source, self.catalog, "windows")["entries"][0]
        self.assertEqual(entry["content_type"], "workflow_template")
        self.assertFalse(entry["executable"])
        self.assertEqual(entry["template"]["prerequisites"], ["verified_agent"])

    def test_source_requires_https_and_ed25519_key(self):
        with self.assertRaises(CatalogError):
            CatalogSource("official-test", "http://plugins.example.test/catalog.json", self.source.public_key, True)
        with self.assertRaises(CatalogError):
            CatalogSource("official-test", "https://plugins.example.test/catalog.json", base64.b64encode(b"short").decode(), True)


if __name__ == "__main__":
    unittest.main()
