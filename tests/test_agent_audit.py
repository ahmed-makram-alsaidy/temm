import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from core.ai_fleet.services.agent_lifecycle import AgentLifecycleService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, AuditRecord
from core.ai_fleet.storage.secret_vault import SecretVault


class AgentAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.executable = Path(self.folder.name) / "agent.exe"
        self.executable.write_text("binary")
        self.agent_id = None

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.agent_id:
                await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.agent_id))
                await session.execute(delete(AgentRecord).where(AgentRecord.id == self.agent_id))
            await session.commit()
        self.folder.cleanup()

    async def test_lifecycle_events_are_audited_without_secrets(self):
        inspection = {"path": str(self.executable.resolve()), "state": "verified", "version": "1.0", "evidence": {"source": "manual"}}
        scanner = AsyncMock()
        scanner.inspect_manual.return_value = inspection
        service = AgentLifecycleService(scanner, SecretVault())
        values = {"name": "Audit Agent", "executable": str(self.executable), "version_probe_args": [], "health_probe_args": [], "invocation_args": [], "input_method": "argument", "output_method": "stdout", "working_directory": "workspace", "supports_pty": False, "supports_interactive": False, "capabilities": ["coding"], "environment_refs": [], "probe_timeout_seconds": 3, "permission_profile": "developer", "auth_required": True, "auth_method": "api_key", "auth_setup_instructions": "use SECRET-VALUE", "description": ""}
        async with AsyncSessionLocal() as session:
            record = await service.create(session, values)
            self.agent_id = record.id
            await service.update(session, record.id, {"user_enabled": False}, record.revision)
            scanner.probe_auth.return_value = {"state": "failed", "method": "api_key", "evidence": {"reason": "SECRET-VALUE"}}
            await service.check_auth(session, record.id)
            rows = (await session.execute(select(AuditRecord).where(AuditRecord.resource_id == record.id).order_by(AuditRecord.sequence))).scalars().all()
        self.assertEqual([row.action for row in rows], ["agent.created", "agent.disabled", "agent.auth_checked"])
        self.assertTrue(all(row.created_at is not None for row in rows))
        details = [json.loads(row.details) for row in rows]
        self.assertTrue(all(item["actor"] == "local_system" for item in details))
        self.assertTrue(all("revision" in item for item in details))
        self.assertNotIn("SECRET-VALUE", json.dumps(details))


if __name__ == "__main__":
    unittest.main()
