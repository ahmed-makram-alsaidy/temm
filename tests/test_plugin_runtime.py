import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.plugin_package import hash_plugin_folder
from core.ai_fleet.services.plugin_runtime import PluginRuntimeService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import PluginRecord


MANIFEST = {
    "id": "runtime-test", "name": "Runtime Test", "version": "1.0.0", "protocol": "1.0",
    "type": "agent", "platforms": ["windows"], "capabilities": [], "permissions": [], "entrypoint": "adapter.py", "rpc_methods": ["detect", "health", "send"],
}


class PluginRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.manager = ProcessManager(graceful_shutdown_seconds=0.1)
        self.service = PluginRuntimeService(self.manager)
        self.plugin_ids = []

    async def asyncTearDown(self):
        await self.manager.shutdown()
        async with AsyncSessionLocal() as session:
            if self.plugin_ids:
                await session.execute(delete(PluginRecord).where(PluginRecord.id.in_(self.plugin_ids)))
                await session.commit()

    async def register(self, folder: Path, plugin_id: str):
        manifest = {**MANIFEST, "id": plugin_id}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        async with AsyncSessionLocal() as session:
            record = PluginRecord(
                id=plugin_id, name=plugin_id, path=str(folder), version="1.0.0", protocol_version="1.0",
                plugin_type="agent", manifest=json.dumps(manifest), permissions="[]", granted_permissions="[]",
                permission_profile="safe", package_hash=hash_plugin_folder(folder), entrypoint=str(folder / "adapter.py"), load_state="eligible",
            )
            session.add(record)
            await session.commit()
        self.plugin_ids.append(plugin_id)

    async def test_successful_plugin_invocation_runs_out_of_process(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("def handle(request):\n    return {'echo': request['params']['value']}\n")
            plugin_id = f"runtime-success-{id(self)}"
            await self.register(path, plugin_id)
            async with AsyncSessionLocal() as session:
                response = await self.service.invoke(session, plugin_id, "send", {"value": "ok"}, 5)
                record = await session.get(PluginRecord, plugin_id)
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"], {"echo": "ok"})
            self.assertEqual(record.load_state, "ready")

    async def test_crash_and_malformed_output_do_not_crash_core(self):
        for suffix, code in [
            ("crash", "raise RuntimeError('import crash')\n"),
            ("noise", "print('noise')\ndef handle(request): return {'ok': True}\n"),
        ]:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                (path / "adapter.py").write_text(code)
                plugin_id = f"runtime-{suffix}-{id(self)}"
                await self.register(path, plugin_id)
                async with AsyncSessionLocal() as session:
                    with self.assertRaises(Exception):
                        await self.service.invoke(session, plugin_id, "send", {}, 5)
                self.assertFalse(self.manager.is_active(plugin_id))

    async def test_timeout_cleans_plugin_process(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("import time\ndef handle(request):\n    time.sleep(30)\n    return {}\n")
            plugin_id = f"runtime-timeout-{id(self)}"
            await self.register(path, plugin_id)
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception):
                    await self.service.invoke(session, plugin_id, "send", {}, 0.1)
            receipt = next(reversed(self.manager._receipts.values()))
            self.assertEqual(receipt["outcome"], "timed_out")

    async def test_cancellation_stops_plugin_process(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("import time\ndef handle(request):\n    time.sleep(30)\n    return {}\n")
            plugin_id = f"runtime-cancel-{id(self)}"
            await self.register(path, plugin_id)
            async with AsyncSessionLocal() as session:
                invocation = asyncio.create_task(self.service.invoke(session, plugin_id, "send", {}, 30))
                task_id = None
                for _ in range(200):
                    task_id = next((item for item in self.manager._active if item.startswith(f"plugin-{plugin_id}-")), None)
                    if task_id:
                        break
                    await asyncio.sleep(0.01)
                self.assertIsNotNone(task_id)
                self.assertTrue(await self.service.cancel(task_id))
                with self.assertRaises(Exception):
                    await invocation
                self.assertFalse(self.manager.is_active(task_id))

    async def test_undeclared_rpc_method_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("def handle(request): return {}\n")
            plugin_id = f"runtime-method-{id(self)}"
            await self.register(path, plugin_id)
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception):
                    await self.service.invoke(session, plugin_id, "quota", {}, 5)
            self.assertFalse(any(item.startswith(f"plugin-{plugin_id}-") for item in self.manager._active))

    async def test_reload_accepts_safe_change_and_blocks_active_invocation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            entrypoint = path / "adapter.py"
            entrypoint.write_text("def handle(request): return {'version': 1}\n")
            plugin_id = f"runtime-reload-{id(self)}"
            await self.register(path, plugin_id)
            async with AsyncSessionLocal() as session:
                entrypoint.write_text("import time\ndef handle(request): time.sleep(30); return {}\n")
                async with session.begin():
                    record = await session.get(PluginRecord, plugin_id)
                    record.package_hash = hash_plugin_folder(path)
                invocation = asyncio.create_task(self.service.invoke(session, plugin_id, "send", {}, 30))
                task_id = None
                for _ in range(200):
                    task_id = next((item for item in self.manager._active if item.startswith(f"plugin-{plugin_id}-")), None)
                    if task_id: break
                    await asyncio.sleep(0.01)
                with self.assertRaises(Exception):
                    await self.service.reload(session, plugin_id)
                await self.service.cancel(task_id)
                with self.assertRaises(Exception):
                    await invocation
            manifest_path = path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["version"] = "1.0.1"
            manifest_path.write_text(json.dumps(manifest))
            entrypoint.write_text("def handle(request): return {'version': 2}\n")
            async with AsyncSessionLocal() as session:
                reloaded = await self.service.reload(session, plugin_id)
                self.assertEqual(reloaded.version, "1.0.1")
                response = await self.service.invoke(session, plugin_id, "send", {}, 5)
                self.assertEqual(response["result"], {"version": 2})

    async def test_reload_rejects_identity_change_without_mutating_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "adapter.py").write_text("def handle(request): return {}\n")
            plugin_id = f"runtime-identity-{id(self)}"
            await self.register(path, plugin_id)
            manifest_path = path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["id"] = "different-plugin"
            manifest_path.write_text(json.dumps(manifest))
            async with AsyncSessionLocal() as session:
                before = await session.get(PluginRecord, plugin_id)
                old_hash = before.package_hash
                with self.assertRaises(Exception):
                    await self.service.reload(session, plugin_id)
                await session.refresh(before)
                self.assertEqual(before.package_hash, old_hash)

    async def test_changed_package_requires_reapproval(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            entrypoint = path / "adapter.py"
            entrypoint.write_text("def handle(request): return {}\n")
            plugin_id = f"runtime-changed-{id(self)}"
            await self.register(path, plugin_id)
            entrypoint.write_text("def handle(request): return {'changed': True}\n")
            async with AsyncSessionLocal() as session:
                with self.assertRaises(Exception):
                    await self.service.invoke(session, plugin_id, "send", {}, 5)
                record = await session.get(PluginRecord, plugin_id)
            self.assertEqual(record.load_state, "changed")


if __name__ == "__main__":
    unittest.main()
