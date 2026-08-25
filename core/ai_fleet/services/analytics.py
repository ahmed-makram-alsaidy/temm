import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import TaskRun, UsageObservationRecord


class AnalyticsService:
    async def aggregate(self, session: AsyncSession, start: datetime, end: datetime, project_id: str | None = None) -> Dict[str, Any]:
        if end <= start or end - start > timedelta(days=366):
            raise DomainError("validation_failed", message="Analytics range must be positive and at most 366 days.")
        statement = select(TaskRun).where(TaskRun.created_at >= start, TaskRun.created_at < end)
        if project_id:
            statement = statement.where(TaskRun.project_id == project_id)
        runs = (await session.execute(statement.order_by(TaskRun.created_at))).scalars().all()
        run_ids = [run.id for run in runs]
        observations = (await session.execute(select(UsageObservationRecord).where(UsageObservationRecord.run_id.in_(run_ids)))).scalars().all() if run_ids else []
        statuses: Dict[str, int] = {}
        fallback_runs = 0
        financials = {"provider_reported_actual_cost": Decimal("0"), "estimated_actual_cost": Decimal("0"), "direct_saving": Decimal("0"), "estimated_avoided_cost": Decimal("0"), "equivalent_api_value": Decimal("0"), "unknown_actual_cost_runs": 0}
        for run in runs:
            statuses[run.status] = statuses.get(run.status, 0) + 1
            if len(json.loads(run.fallback_chain or "[]")) > 1:
                fallback_runs += 1
            evidence = json.loads(run.financials_json or "{}")
            actual = evidence.get("actual_cost", {})
            value = evidence.get("value", {})
            amount = actual.get("amount")
            if amount is None:
                financials["unknown_actual_cost_runs"] += 1
            elif actual.get("provenance") == "provider_reported":
                financials["provider_reported_actual_cost"] += Decimal(amount)
            else:
                financials["estimated_actual_cost"] += Decimal(amount)
            if value.get("amount") is not None and value.get("category") in {"direct_saving", "estimated_avoided_cost", "equivalent_api_value"}:
                financials[value["category"]] += Decimal(value["amount"])
        usage = {source: {dimension: 0 for dimension in ["requests", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]} for source in ["provider_reported", "measured", "estimated"]}
        unknown_usage_observations = 0
        for observation in observations:
            if observation.source == "unknown":
                unknown_usage_observations += 1
                continue
            for dimension in usage[observation.source]:
                usage[observation.source][dimension] += getattr(observation, dimension) or 0
        financial_payload = {key: str(value) if isinstance(value, Decimal) else value for key, value in financials.items()}
        return {"range": {"start": start.isoformat(), "end": end.isoformat(), "end_exclusive": True}, "runs": {"total": len(runs), "statuses": statuses, "fallback_runs": fallback_runs}, "usage_by_provenance": usage, "unknown_usage_observations": unknown_usage_observations, "financials": financial_payload}


analytics_service = AnalyticsService()
