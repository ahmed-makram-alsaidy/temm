import json
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import BudgetRecord, ModelRecord, TaskRun


class BudgetService:
    async def create(self, session: AsyncSession, values: Dict[str, Any]) -> BudgetRecord:
        try:
            amount = Decimal(str(values["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise DomainError("validation_failed", message="Budget amount is invalid.") from exc
        currency = values.get("currency", "USD").upper()
        period = values.get("period", "monthly")
        scope_type = values.get("scope_type", "fleet")
        scope_id = values.get("scope_id")
        threshold = float(values.get("alert_threshold", 80.0))
        if amount <= 0 or len(currency) != 3 or not currency.isalpha() or period != "monthly" or scope_type not in {"fleet", "workspace", "provider"} or not 1 <= threshold <= 100:
            raise DomainError("validation_failed", message="Budget configuration is invalid.")
        if scope_type != "fleet" and not scope_id:
            raise DomainError("validation_failed", message="Scoped budgets require a scope id.")
        record = BudgetRecord(id=f"budget-{uuid.uuid4().hex[:12]}", name=values["name"], amount=str(amount), currency=currency, period=period, scope_type=scope_type, scope_id=scope_id, alert_threshold=threshold, enabled=values.get("enabled", True))
        session.add(record)
        await session.commit()
        return record

    async def list(self, session: AsyncSession) -> List[BudgetRecord]:
        return (await session.execute(select(BudgetRecord).order_by(BudgetRecord.created_at.desc()))).scalars().all()

    async def status(self, session: AsyncSession, budget_id: str, at: Optional[datetime] = None) -> Dict[str, Any]:
        budget = await session.get(BudgetRecord, budget_id)
        if not budget:
            raise DomainError("resource_not_found", message="Budget was not found.")
        moment = at or datetime.utcnow()
        start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        statement = select(TaskRun).where(TaskRun.created_at >= start, TaskRun.created_at < end)
        if budget.scope_type == "workspace":
            statement = statement.where(TaskRun.workspace_id == budget.scope_id)
        rows = (await session.execute(statement)).scalars().all()
        if budget.scope_type == "provider":
            model_ids = {row.selected_model_id for row in rows if row.selected_model_id}
            models = (await session.execute(select(ModelRecord).where(ModelRecord.id.in_(model_ids)))).scalars().all() if model_ids else []
            providers = {model.id: model.provider for model in models}
            rows = [row for row in rows if providers.get(row.selected_model_id) == budget.scope_id]
        reported = Decimal("0")
        estimated = Decimal("0")
        unknown = 0
        included = 0
        for run in rows:
            evidence = json.loads(run.financials_json or "{}")
            actual = evidence.get("actual_cost", {})
            if actual.get("currency") not in {None, budget.currency}:
                continue
            amount = actual.get("amount")
            provenance = actual.get("provenance", "unknown")
            if amount is None or provenance == "unknown":
                unknown += 1
                continue
            included += 1
            if provenance == "provider_reported":
                reported += Decimal(amount)
            else:
                estimated += Decimal(amount)
        limit = Decimal(budget.amount)
        reported_pct = float(reported / limit * 100)
        estimated_pct = float((reported + estimated) / limit * 100)
        threshold = float(budget.alert_threshold)
        return {"budget": budget.to_dict(), "period_start": start.isoformat(), "period_end": end.isoformat(), "provider_reported_spend": str(reported), "estimated_spend": str(estimated), "currency": budget.currency, "reported_utilization_percentage": round(reported_pct, 2), "estimated_utilization_percentage": round(estimated_pct, 2), "reported_alert": reported_pct >= threshold, "estimated_alert": estimated_pct >= threshold, "alert_basis": "provider_reported" if reported_pct >= threshold else "reported_plus_estimated" if estimated_pct >= threshold else "none", "unknown_run_count": unknown, "included_run_count": included}


budget_service = BudgetService()
