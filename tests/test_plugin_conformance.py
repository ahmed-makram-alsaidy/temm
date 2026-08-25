import json
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.plugin_package import hash_plugin_folder
from core.ai_fleet.services.plugin_conformance import PluginConformanceService
from core.ai_fleet.services.plugin_runtime import PluginRuntimeService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import PluginRecord


class PluginConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.manager = ProcessManager(graceful_shutdown_seconds=0.1)
        self.service = PluginConformanceService(PluginRuntimeService(self.manager))
        self.ids = []

    async def asyncTearDown(self):
        await self.manager.shutdown()
        async with AsyncSessionLocal() as session:
            for plugin_id in self.ids:
                record = await session.get(PluginRecord, plugin_id)
                if record:
                    await session.delete(record)
            await session.commit()

    async def register(self, folder, plugin_id, methods):
        manifest = {"id": plugin_id, "name": plugin_id, "version": "1.0.0", "protocol": "1.0", "type": "agent", "platforms": ["windows"], "capabilities": [], "permissions": [], "entrypoint": "adapter.py", "rpc_methods": methods}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        async with AsyncSessionLocal() as session:
            session.add(PluginRecord(id=plugin_id, name=plugin_id, path=str(folder), version="1.0.0", protocol_version="1.0", plugin_type="agent", manifest=json.dumps(manifest), permissions="[]", granted_permissions="[]", permission_profile="safe", package_hash=hash_plugin_folder(folder), entrypoint=str(folder / "adapter.py"), load_state="eligible"))
            await session.commit()
        self.ids.append(plugin_id)

    async def test_all_declared_methods_produce_machine_readable_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("def handle(request): return {'method': request['method']}\n")
            plugin_id = f"conformance-pass-{id(self)}"
            await self.register(path, plugin_id, ["detect", "version", "health"])
            async with AsyncSessionLocal() as session:
                result = await self.service.run(session, plugin_id)
        self.assertTrue(result["passed"], result)
        names = {check["name"] for check in result["checks"]}
        self.assertTrue({"manifest", "compatibility", "package_integrity", "permissions", "rpc.detect", "rpc.version", "rpc.health"} <= names)

    async def test_failed_method_is_reported_not_synthesized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("def handle(request):\n    if request['method']=='health': raise RuntimeError('bad health')\n    return {}\n")
            plugin_id = f"conformance-fail-{id(self)}"
            await self.register(path, plugin_id, ["detect", "health"])
            async with AsyncSessionLocal() as session:
                result = await self.service.run(session, plugin_id)
        self.assertFalse(result["passed"])
        health = next(check for check in result["checks"] if check["name"] == "rpc.health")
        self.assertFalse(health["passed"])
        self.assertIn("error", health)


if __name__ == "__main__":
    unittest.main()
