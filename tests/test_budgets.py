import json
import unittest
from datetime import datetime

import httpx
from sqlalchemy import delete

from core.ai_fleet.main import app
from core.ai_fleet.services.budgets import BudgetService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import BudgetRecord, TaskRun


class BudgetServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.budget_id = None
        self.run_ids = [f"budget-run-{id(self)}-{index}" for index in range(3)]
        async with AsyncSessionLocal() as session:
            session.add_all([
                TaskRun(id=self.run_ids[0], prompt="reported", status="completed", cost_provenance="provider_reported", financials_json=json.dumps({"actual_cost": {"amount": "40.00", "currency": "USD", "provenance": "provider_reported"}})),
                TaskRun(id=self.run_ids[1], prompt="estimated", status="completed", cost_provenance="estimated", financials_json=json.dumps({"actual_cost": {"amount": "30.00", "currency": "USD", "provenance": "estimated"}})),
                TaskRun(id=self.run_ids[2], prompt="unknown", status="completed", cost_provenance="unknown", financials_json=json.dumps({"actual_cost": {"amount": None, "currency": None, "provenance": "unknown"}})),
            ])
            await session.commit()
        self.service = BudgetService()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(self.run_ids)))
            if self.budget_id:
                await session.execute(delete(BudgetRecord).where(BudgetRecord.id == self.budget_id))
            await session.commit()

    async def test_status_separates_reported_estimated_and_unknown(self):
        async with AsyncSessionLocal() as session:
            budget = await self.service.create(session, {"name": "Monthly", "amount": "100", "currency": "USD", "alert_threshold": 60})
            self.budget_id = budget.id
            status = await self.service.status(session, budget.id, datetime.utcnow())
        self.assertEqual(status["provider_reported_spend"], "40.00")
        self.assertEqual(status["estimated_spend"], "30.00")
        self.assertEqual(status["unknown_run_count"], 1)
        self.assertFalse(status["reported_alert"])
        self.assertTrue(status["estimated_alert"])
        self.assertEqual(status["alert_basis"], "reported_plus_estimated")

    async def test_invalid_scoped_budget_is_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(Exception):
                await self.service.create(session, {"name": "Provider", "amount": "10", "scope_type": "provider"})


class BudgetApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.created_id = None
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        if self.created_id:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(BudgetRecord).where(BudgetRecord.id == self.created_id))
                await session.commit()

    async def test_create_list_and_status_contract(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            created = await client.post("/api/budgets", json={"name": "Fleet", "amount": "200", "currency": "USD", "alert_threshold": 80})
            self.assertEqual(created.status_code, 200, created.text)
            self.created_id = created.json()["id"]
            listing = await client.get("/api/budgets")
            status = await client.get(f"/api/budgets/{self.created_id}/status")
        self.assertTrue(any(item["id"] == self.created_id for item in listing.json()))
        self.assertEqual(status.json()["budget"]["id"], self.created_id)
        self.assertIn("unknown_run_count", status.json())


if __name__ == "__main__":
    unittest.main()
