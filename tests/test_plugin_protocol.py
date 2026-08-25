import tempfile
import unittest
from pathlib import Path

import httpx

from core.ai_fleet.main import app
from core.ai_fleet.plugin_protocol import PluginManifest, PluginPermission, PluginType, negotiate_protocol


VALID = {
    "id": "example-agent",
    "name": "Example Agent",
    "version": "1.2.3",
    "protocol": "1.0",
    "type": "agent",
    "platforms": ["windows", "linux"],
    "capabilities": ["coding", "shell"],
    "permissions": ["filesystem_read", "shell"],
    "entrypoint": "adapter.py",
    "rpc_methods": ["detect", "version", "auth", "health", "start", "send", "stream", "cancel", "usage", "quota"],
}


class PluginProtocolTests(unittest.TestCase):
    def test_valid_manifest_is_normalized(self):
        manifest = PluginManifest.parse(VALID)
        self.assertEqual(manifest.plugin_type, PluginType.AGENT)
        self.assertIn(PluginPermission.SHELL, manifest.permissions)
        self.assertEqual(manifest.to_dict()["protocol"], "1.0")

    def test_protocol_negotiation_matrix(self):
        self.assertTrue(negotiate_protocol("1.0"))
        self.assertTrue(negotiate_protocol(">=1.0,<2.0"))
        self.assertFalse(negotiate_protocol("2.0"))
        self.assertFalse(negotiate_protocol(">=0.5,<1.0"))

    def test_invalid_protocol_type_capability_permission_and_entrypoint(self):
        cases = [
            {**VALID, "protocol": ">=1.x"},
            {**VALID, "type": "theme"},
            {**VALID, "capabilities": ["magic"]},
            {**VALID, "permissions": ["root"]},
            {**VALID, "entrypoint": "../adapter.py"},
            {**VALID, "version": "latest"},
        ]
        for value in cases:
            with self.assertRaises(ValueError, msg=value):
                PluginManifest.parse(value)


class PluginInspectionProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from core.ai_fleet.storage.database import init_db
        await init_db()

    async def test_inspection_validates_protocol_without_loading_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            import json
            (path / "manifest.json").write_text(json.dumps(VALID))
            (path / "adapter.py").write_text("raise RuntimeError('must not load')")
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/plugins/inspect", json={"folder_path": str(path)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        self.assertFalse(response.json()["executes_code"])
        self.assertEqual(response.json()["protocol_version"], "1.0")
        self.assertEqual(len(response.json()["package_hash"]), 64)
        self.assertTrue(response.json()["entrypoint"].endswith("adapter.py"))

    async def test_registration_requires_exact_allowed_grants_and_records_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            import json
            manifest = {**VALID, "id": f"registered-{id(self)}"}
            (path / "manifest.json").write_text(json.dumps(manifest))
            (path / "adapter.py").write_text("raise RuntimeError('must not load')")
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.post("/api/plugins/register", json={"folder_path": str(path), "permission_profile": "developer", "granted_permissions": []})
                registered = await client.post("/api/plugins/register", json={"folder_path": str(path), "permission_profile": "developer", "granted_permissions": manifest["permissions"]})
            self.assertEqual(missing.status_code, 409)
            self.assertEqual(registered.status_code, 200)
            payload = registered.json()
            self.assertEqual(payload["load_state"], "eligible")
            self.assertEqual(len(payload["package_hash"]), 64)
            from core.ai_fleet.storage.database import AsyncSessionLocal
            from core.ai_fleet.storage.models import PluginRecord
            async with AsyncSessionLocal() as session:
                record = await session.get(PluginRecord, manifest["id"])
                await session.delete(record)
                await session.commit()

    async def test_incompatible_plugin_registers_but_stays_unloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            import json
            manifest = {**VALID, "id": f"incompatible-{id(self)}", "protocol": "2.0"}
            (path / "manifest.json").write_text(json.dumps(manifest))
            (path / "adapter.py").write_text("def handle(request): return {}")
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                inspected = await client.post("/api/plugins/inspect", json={"folder_path": str(path)})
                registered = await client.post("/api/plugins/register", json={"folder_path": str(path), "permission_profile": "developer", "granted_permissions": manifest["permissions"]})
            self.assertFalse(inspected.json()["compatible"])
            self.assertEqual(registered.status_code, 200)
            self.assertEqual(registered.json()["load_state"], "incompatible")
            from core.ai_fleet.storage.database import AsyncSessionLocal
            from core.ai_fleet.storage.models import PluginRecord
            async with AsyncSessionLocal() as session:
                record = await session.get(PluginRecord, manifest["id"])
                await session.delete(record)
                await session.commit()

    async def test_legacy_implicit_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            import json
            (path / "manifest.json").write_text(json.dumps({"id": "legacy", "name": "Legacy"}))
            (path / "adapter.py").write_text("")
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/plugins/inspect", json={"folder_path": str(path)})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
