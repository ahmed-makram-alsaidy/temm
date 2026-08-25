import json
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import TaskRun
from .latency import latency_service
from .usage import usage_service


class RunComparisonService:
    async def compare(self, session: AsyncSession, run_ids: List[str]) -> Dict[str, Any]:
        if len(run_ids) < 2 or len(run_ids) > 10 or len(set(run_ids)) != len(run_ids):
            raise DomainError("validation_failed", message="Compare between two and ten distinct runs.")
        runs = []
        for run_id in run_ids:
            run = await session.get(TaskRun, run_id)
            if not run:
                raise DomainError("resource_not_found", message=f"Run was not found: {run_id}.")
            runs.append(run)
        usage = {run.id: await usage_service.aggregate(session, run.id) for run in runs}
        latency = {run.id: await latency_service.aggregate(session, run.id) for run in runs}
        metrics = {
            "duration_ms": self._observed_metric(runs, latency, "latency", "duration_ms"),
            "input_tokens": self._observed_metric(runs, usage, "usage", "input_tokens"),
            "output_tokens": self._observed_metric(runs, usage, "usage", "output_tokens"),
            "actual_cost": self._cost_metric(runs, "actual_cost"),
            "reference_cost": self._cost_metric(runs, "reference_cost"),
            "value": self._value_metric(runs),
            "quality": self._quality_metric(runs),
        }
        return {"run_ids": run_ids, "runs": [{"id": run.id, "status": run.status, "model_id": run.selected_model_id, "agent_id": run.selected_agent_id} for run in runs], "metrics": metrics}

    def _observed_metric(self, runs: List[TaskRun], aggregates: Dict[str, Dict[str, Any]], group: str, dimension: str) -> Dict[str, Any]:
        values = [{"run_id": run.id, "value": aggregates[run.id][group][dimension], "provenance": aggregates[run.id]["provenance"][dimension]} for run in runs]
        return self._compatible(values, require_same_provenance=True)

    def _cost_metric(self, runs: List[TaskRun], key: str) -> Dict[str, Any]:
        values = []
        for run in runs:
            item = json.loads(run.financials_json or "{}").get(key, {})
            values.append({"run_id": run.id, "value": item.get("amount"), "currency": item.get("currency"), "provenance": item.get("provenance", "unknown"), "method": item.get("method")})
        return self._compatible(values, require_same_provenance=True, compatible_fields=["currency"])

    def _value_metric(self, runs: List[TaskRun]) -> Dict[str, Any]:
        values = []
        for run in runs:
            item = json.loads(run.financials_json or "{}").get("value", {})
            values.append({"run_id": run.id, "value": item.get("amount"), "currency": item.get("currency"), "provenance": item.get("provenance", "unknown"), "category": item.get("category"), "method": item.get("method")})
        return self._compatible(values, require_same_provenance=True, compatible_fields=["currency", "category"])

    def _quality_metric(self, runs: List[TaskRun]) -> Dict[str, Any]:
        values = [{"run_id": run.id, "value": run.quality_eval_score, "provenance": run.quality_provenance} for run in runs]
        return self._compatible(values, require_same_provenance=True)

    def _compatible(self, values: List[Dict[str, Any]], require_same_provenance: bool, compatible_fields: List[str] | None = None) -> Dict[str, Any]:
        if any(item["value"] is None or item["provenance"] == "unknown" for item in values):
            return {"comparable": False, "reason": "missing_or_unknown_value", "values": values}
        fields = list(compatible_fields or [])
        if require_same_provenance:
            fields.append("provenance")
        for field in fields:
            if len({item.get(field) for item in values}) != 1:
                return {"comparable": False, "reason": f"incompatible_{field}", "values": values}
        return {"comparable": True, "reason": "commensurable", "values": values}


run_comparison_service = RunComparisonService()
