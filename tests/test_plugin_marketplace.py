import base64
import io
import json
import tempfile
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.ai_fleet.errors import DomainError
from core.ai_fleet.plugin_package import hash_plugin_folder
from core.ai_fleet.services.plugin_marketplace import PluginMarketplaceService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ApprovalRecord, BenchmarkCaseRecord, BenchmarkSuiteVersionRecord, PluginCatalogSourceRecord, PluginRecord, WorkflowTemplateVersionRecord
from core.ai_fleet.url_safety import UrlSafetyService


class PluginMarketplaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "installed"
        self.source_id = f"market-{uuid.uuid4().hex[:10]}"
        self.plugin_id = f"agent-{uuid.uuid4().hex[:10]}"
        self.package, self.folder_hash = self.make_package()
        self.benchmark_version_ids = []
        self.workflow_template_ids = []
        self.package_url = "https://packages.example.test/plugin.zip"
        self.index_url = "https://catalog.example.test/index.json"
        self.responses = {self.package_url: self.package}

        async def fetch_bytes(url, policy):
            content = self.responses[url]
            return {"content": content, "content_type": "application/json" if url.endswith(".json") else "application/zip", "content_length": len(content), "redirect_chain": [url]}

        async def fetch_json(url, policy):
            raise AssertionError("refresh is not used in lifecycle tests")

        safety = UrlSafetyService(lambda host: ["93.184.216.34"])
        self.service = PluginMarketplaceService(self.root, safety, fetch_json, fetch_bytes)
        self.catalog_entry = {
            "manifest": self.manifest(),
            "author": "Marketplace Test",
            "source_code_url": "https://code.example.test/plugin",
            "package": {
                "url": self.package_url,
                "sha256": __import__("hashlib").sha256(self.package).hexdigest(),
                "folder_sha256": self.folder_hash,
                "size": len(self.package),
            },
            "compatible": True,
            "platform_supported": True,
            "permissions": ["filesystem_read"],
            "reputation": "unverified",
            "requires_permission_review": True,
            "rollback": {"retain_previous_package": True, "previous_hash_required": True},
        }
        async with AsyncSessionLocal() as session:
            session.add(PluginCatalogSourceRecord(id=self.source_id, index_url=self.index_url, public_key="x" * 44, enabled=True, last_state="verified", catalog_json=json.dumps({"entries": [self.catalog_entry]}), verified_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(hours=1)))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            plugin = await session.get(PluginRecord, self.plugin_id)
            if plugin:
                await session.delete(plugin)
            for template_id in self.workflow_template_ids:
                record = await session.get(WorkflowTemplateVersionRecord, template_id)
                if record:
                    await session.delete(record)
            for version_id in self.benchmark_version_ids:
                await session.execute(__import__("sqlalchemy").delete(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id == version_id))
                record = await session.get(BenchmarkSuiteVersionRecord, version_id)
                if record:
                    await session.delete(record)
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            if source:
                await session.delete(source)
            await session.commit()
        self.folder.cleanup()

    def manifest(self, version="1.0.0"):
        return {
            "id": self.plugin_id,
            "name": "Marketplace Agent",
            "version": version,
            "protocol": "1.0",
            "type": "agent",
            "platforms": ["windows", "linux", "macos"],
            "capabilities": ["coding"],
            "permissions": ["filesystem_read"],
            "entrypoint": "adapter.py",
            "rpc_methods": ["detect", "health"],
        }

    def make_package(self, version="1.0.0"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "manifest.json").write_text(json.dumps(self.manifest(version)), encoding="utf-8")
            (path / "adapter.py").write_text("def handle(request): return {}\n", encoding="utf-8")
            folder_hash = hash_plugin_folder(path)
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(path / "manifest.json", "manifest.json")
                archive.write(path / "adapter.py", "adapter.py")
            return output.getvalue(), folder_hash

    async def approval(self, action_type, scope_type, scope_id):
        approval_id = f"approval-{uuid.uuid4().hex[:12]}"
        async with AsyncSessionLocal() as session:
            session.add(ApprovalRecord(id=approval_id, action_type=action_type, scope_type=scope_type, scope_id=scope_id, summary="Marketplace test", status="approved", expires_at=datetime.utcnow() + timedelta(minutes=5)))
            await session.commit()
        return approval_id

    async def test_refresh_caches_only_valid_signed_catalog(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        catalog = {"schema_version": "1.0", "source_id": self.source_id, "generated_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(), "entries": [{"manifest": self.manifest(), "author": "Marketplace Test", "source_code_url": "https://code.example.test/plugin", "package": self.catalog_entry["package"]}]}
        signing_service = __import__("core.ai_fleet.plugin_catalog", fromlist=["plugin_catalog"]).plugin_catalog
        catalog["signature"] = base64.b64encode(private.sign(signing_service.canonical_payload(catalog))).decode()

        async def fetch_json(url, policy):
            return {"json": catalog, "content_type": "application/json", "content_length": 1024, "redirect_chain": [url]}

        service = PluginMarketplaceService(self.root, UrlSafetyService(lambda host: ["93.184.216.34"]), fetch_json, self.service.fetch_bytes)
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            source.public_key = base64.b64encode(public).decode()
            await session.commit()
            result = await service.refresh(session, self.source_id, "windows")
            self.assertTrue(result["verified"])
            self.assertEqual(len(await service.browse(session, self.source_id)), 1)
            catalog["entries"][0]["author"] = "Tampered"
            with self.assertRaises(DomainError):
                await service.refresh(session, self.source_id, "windows")
            await session.refresh(source)
            self.assertEqual(source.last_state, "failed")
            self.assertEqual(await service.browse(session, self.source_id), [])

    async def test_signed_benchmark_pack_import_preserves_marketplace_provenance(self):
        payload = {"suite_key": f"market-pack-{uuid.uuid4().hex[:8]}", "name": "Marketplace Pack", "category": "coding", "cases": [{"case_key": "one", "prompt": "Return JSON", "expected_behavior": "Valid JSON", "evaluator_type": "json_schema", "evaluator_config": {"type": "object"}, "category": "coding", "difficulty": "easy", "weight": 1}]}
        package = json.dumps(payload).encode()
        url = "https://packages.example.test/benchmark.json"
        self.responses[url] = package
        entry = {"content_type": "benchmark_pack", "identity": {"id": "market-pack", "version": "1.0.0"}, "pack": {"id": "market-pack", "version": "1.0.0", "schema_version": "1.0", "category": "coding", "name": "Marketplace Pack"}, "author": "Pack Author", "source_code_url": "https://code.example.test/pack", "package": {"url": url, "sha256": __import__("hashlib").sha256(package).hexdigest(), "size": len(package), "media_type": "application/json"}, "compatible": True, "platform_supported": True, "permissions": [], "reputation": "unverified", "requires_permission_review": False, "executable": False}
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            source.catalog_json = json.dumps({"entries": [entry]})
            await session.commit()
        approval = await self.approval("network", "benchmark_pack_import", f"{self.source_id}:market-pack:1.0.0")
        async with AsyncSessionLocal() as session:
            version = await self.service.import_benchmark_pack(session, self.source_id, "market-pack", "1.0.0", approval)
            self.benchmark_version_ids.append(version.id)
            self.assertEqual(version.provenance, "marketplace")
            self.assertEqual(version.source_uri, url)
            cases = (await session.execute(__import__("sqlalchemy").select(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id == version.id))).scalars().all()
            self.assertEqual(cases[0].provenance, "marketplace")

    async def test_signed_workflow_template_import_is_versioned_and_non_executable(self):
        payload = {"schema_version": "1.0", "template_key": "market-flow", "version": "1.0.0", "name": "Market Flow", "prerequisites": ["verified_coding_agent"], "gate_ids": ["tests"], "executable": False, "definition": {"nodes": [{"id": "task", "type": "task", "inputs": [], "outputs": [{"name": "task", "data_type": "task"}]}, {"id": "output", "type": "output", "inputs": [{"name": "task", "data_type": "task"}], "outputs": []}], "edges": [{"source_node": "task", "source_port": "task", "target_node": "output", "target_port": "task"}], "inputs": [], "outputs": [{"name": "result", "data_type": "any"}]}}
        package = json.dumps(payload).encode()
        url = "https://packages.example.test/workflow.json"
        self.responses[url] = package
        entry = {"content_type": "workflow_template", "identity": {"id": "market-flow", "version": "1.0.0"}, "template": {"id": "market-flow", "version": "1.0.0", "schema_version": "1.0", "name": "Market Flow", "prerequisites": ["verified_coding_agent"], "gate_ids": ["tests"]}, "author": "Flow Author", "source_code_url": "https://code.example.test/flow", "package": {"url": url, "sha256": __import__("hashlib").sha256(package).hexdigest(), "size": len(package), "media_type": "application/json"}, "compatible": True, "platform_supported": True, "permissions": [], "reputation": "unverified", "requires_permission_review": False, "executable": False}
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            source.catalog_json = json.dumps({"entries": [entry]})
            await session.commit()
        approval = await self.approval("network", "workflow_template_import", f"{self.source_id}:market-flow:1.0.0")
        async with AsyncSessionLocal() as session:
            record = await self.service.import_workflow_template(session, self.source_id, "market-flow", "1.0.0", approval)
            self.workflow_template_ids.append(record.id)
            self.assertEqual(record.provenance, "marketplace")
            self.assertFalse(record.executable)
            self.assertEqual(json.loads(record.prerequisites_json), ["verified_coding_agent"])
            self.assertEqual(record.source_uri, url)

    async def test_install_requires_scoped_approval_and_persists_provenance(self):
        scope = f"{self.source_id}:{self.plugin_id}:1.0.0"
        approval_id = await self.approval("network", "plugin_install", scope)
        async with AsyncSessionLocal() as session:
            record = await self.service.install(session, self.source_id, self.plugin_id, "1.0.0", ["filesystem_read"], "developer", approval_id)
            self.assertEqual(record.source_type, "marketplace")
            self.assertEqual(record.source_id, self.source_id)
            self.assertEqual(record.package_hash, self.folder_hash)
            self.assertTrue(Path(record.path).is_dir())
            self.assertEqual(record.load_state, "eligible")

    async def test_install_rejects_permission_mismatch_and_archive_traversal(self):
        scope = f"{self.source_id}:{self.plugin_id}:1.0.0"
        approval_id = await self.approval("network", "plugin_install", scope)
        async with AsyncSessionLocal() as session:
            with self.assertRaises(DomainError):
                await self.service.install(session, self.source_id, self.plugin_id, "1.0.0", [], "developer", approval_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../escape.py", "bad")
        malicious = output.getvalue()
        self.responses[self.package_url] = malicious
        self.catalog_entry["package"]["sha256"] = __import__("hashlib").sha256(malicious).hexdigest()
        self.catalog_entry["package"]["size"] = len(malicious)
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            source.catalog_json = json.dumps({"entries": [self.catalog_entry]})
            await session.commit()
        approval_id = await self.approval("network", "plugin_install", scope)
        async with AsyncSessionLocal() as session:
            with self.assertRaisesRegex(DomainError, "unsafe path"):
                await self.service.install(session, self.source_id, self.plugin_id, "1.0.0", ["filesystem_read"], "developer", approval_id)
        self.assertFalse((self.root / self.plugin_id / "1.0.0").exists())
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("..\\escape.py", "bad")
        with self.assertRaisesRegex(DomainError, "unsafe path"):
            self.service._extract(output.getvalue(), self.plugin_id)

    async def test_update_retains_previous_version_and_rollback_revalidates_it(self):
        install_scope = f"{self.source_id}:{self.plugin_id}:1.0.0"
        install_approval = await self.approval("network", "plugin_install", install_scope)
        async with AsyncSessionLocal() as session:
            await self.service.install(session, self.source_id, self.plugin_id, "1.0.0", ["filesystem_read"], "developer", install_approval)
        package, folder_hash = self.make_package("1.1.0")
        self.responses[self.package_url] = package
        update = {**self.catalog_entry, "manifest": self.manifest("1.1.0"), "package": {**self.catalog_entry["package"], "sha256": __import__("hashlib").sha256(package).hexdigest(), "folder_sha256": folder_hash, "size": len(package)}}
        async with AsyncSessionLocal() as session:
            source = await session.get(PluginCatalogSourceRecord, self.source_id)
            source.catalog_json = json.dumps({"entries": [update]})
            await session.commit()
        update_approval = await self.approval("network", "plugin_install", f"{self.source_id}:{self.plugin_id}:1.1.0")
        async with AsyncSessionLocal() as session:
            updated = await self.service.install(session, self.source_id, self.plugin_id, "1.1.0", ["filesystem_read"], "developer", update_approval)
            self.assertEqual(updated.version, "1.1.0")
            self.assertTrue(Path(updated.previous_path).is_dir())
        rollback_approval = await self.approval("destructive", "plugin_rollback", self.plugin_id)
        async with AsyncSessionLocal() as session:
            rolled_back = await self.service.rollback(session, self.plugin_id, rollback_approval)
            self.assertEqual(rolled_back.version, "1.0.0")
            self.assertEqual(rolled_back.package_hash, self.folder_hash)

    async def test_remove_requires_destructive_approval(self):
        scope = f"{self.source_id}:{self.plugin_id}:1.0.0"
        install_approval = await self.approval("network", "plugin_install", scope)
        async with AsyncSessionLocal() as session:
            await self.service.install(session, self.source_id, self.plugin_id, "1.0.0", ["filesystem_read"], "developer", install_approval)
        remove_approval = await self.approval("destructive", "plugin_remove", self.plugin_id)
        async with AsyncSessionLocal() as session:
            await self.service.remove(session, self.plugin_id, remove_approval)
            self.assertIsNone(await session.get(PluginRecord, self.plugin_id))
        self.assertFalse((self.root / self.plugin_id / "1.0.0").exists())


if __name__ == "__main__":
    unittest.main()
