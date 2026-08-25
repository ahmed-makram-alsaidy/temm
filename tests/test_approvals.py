import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.approvals import ApprovalService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ApprovalRecord, WorkspaceRecord
from core.ai_fleet.storage.secret_vault import secret_vault


class ApprovalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.service = ApprovalService()
        self.ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.ids:
                await session.execute(delete(ApprovalRecord).where(ApprovalRecord.id.in_(self.ids)))
                await session.commit()

    async def test_approval_is_scoped_single_use(self):
        async with AsyncSessionLocal() as session:
            record = await self.service.request(session, action_type="command", scope_type="workspace", scope_id="one", summary="Run command", details={})
            self.ids.append(record.id)
            await self.service.decide(session, record.id, True)
            with self.assertRaises(Exception):
                await self.service.consume(session, record.id, "command", "workspace", "two")
            consumed = await self.service.consume(session, record.id, "command", "workspace", "one")
            self.assertEqual(consumed.status, "consumed")
            with self.assertRaises(Exception):
                await self.service.consume(session, record.id, "command", "workspace", "one")

    async def test_approval_details_are_redacted(self):
        secret_vault.set_key("approval-test-secret", "approval-secret-82937465")
        try:
            async with AsyncSessionLocal() as session:
                record = await self.service.request(session, action_type="command", scope_type="workspace", scope_id="one", summary="Sensitive", details={"command": "tool --key approval-secret-82937465"})
                self.ids.append(record.id)
                self.assertNotIn("approval-secret-82937465", record.details)
                self.assertIn("[REDACTED]", record.details)
        finally:
            secret_vault.delete_key("approval-test-secret")

    async def test_expired_approval_cannot_be_decided(self):
        async with AsyncSessionLocal() as session:
            record = ApprovalRecord(id=f"expired-{id(self)}", action_type="command", scope_type="workspace", scope_id="one", summary="Expired", expires_at=datetime.utcnow() - timedelta(seconds=1))
            self.ids.append(record.id)
            session.add(record)
            await session.commit()
            with self.assertRaises(Exception):
                await self.service.decide(session, record.id, True)
            self.assertEqual(record.status, "expired")


@unittest.skipUnless(os.name == "nt", "Terminal approval execution requires Windows command shells.")
class TerminalApprovalApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.workspace_id = f"approval-workspace-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Approval Workspace", path=str(Path(self.folder.name).resolve()), permission_profile="developer", allowed_shells='["powershell"]'))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)
        self.approval_ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ApprovalRecord).where(ApprovalRecord.id.in_(self.approval_ids))) if self.approval_ids else None
            workspace = await session.get(WorkspaceRecord, self.workspace_id)
            if workspace:
                await session.delete(workspace)
            await session.commit()
        self.folder.cleanup()

    async def test_terminal_requires_and_consumes_scoped_approval(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            missing = await client.post("/api/terminal/run", json={"command": "python --version", "shell": "powershell", "workspace_id": self.workspace_id})
            requested = await client.post("/api/approvals", json={"action_type": "command", "scope_type": "workspace", "scope_id": self.workspace_id, "summary": "Version command"})
            approval = requested.json()
            self.approval_ids.append(approval["id"])
            await client.post(f"/api/approvals/{approval['id']}/decision", json={"approve": True})
            executed = await client.post("/api/terminal/run", json={"command": "python --version", "shell": "powershell", "workspace_id": self.workspace_id, "approval_id": approval["id"]})
            replay = await client.post("/api/terminal/run", json={"command": "python --version", "shell": "powershell", "workspace_id": self.workspace_id, "approval_id": approval["id"]})
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(executed.status_code, 200)
        self.assertTrue(executed.json()["success"])
        self.assertEqual(replay.status_code, 403)


if __name__ == "__main__":
    unittest.main()
