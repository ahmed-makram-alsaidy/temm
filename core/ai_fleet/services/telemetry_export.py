import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..security import SensitiveDataRedactor
from ..storage.models import LatencyObservationRecord, TaskRun, UsageObservationRecord
from ..storage.secret_vault import secret_vault
from .audit import audit_service


class TelemetryExportService:
    async def export(self, session: AsyncSession, start: datetime, end: datetime, format: str) -> str:
        if end <= start or end - start > timedelta(days=366) or format not in {"json", "csv"}:
            raise DomainError("validation_failed", message="Export range or format is invalid.")
        runs = (await session.execute(select(TaskRun).where(TaskRun.created_at >= start, TaskRun.created_at < end).order_by(TaskRun.created_at, TaskRun.id).limit(10001))).scalars().all()
        if len(runs) > 10000:
            raise DomainError("resource_conflict", message="Export exceeds the 10,000 run limit.")
        rows = [self._row(run) for run in runs]
        redacted = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact(rows)
        await audit_service.append(session, action="telemetry.exported", resource_type="telemetry", resource_id="runs", details={"actor": "local_system", "format": format, "start": start.isoformat(), "end": end.isoformat(), "row_count": len(rows)})
        await session.commit()
        if format == "json":
            return json.dumps({"schema_version": "1.0", "range": {"start": start.isoformat(), "end": end.isoformat(), "end_exclusive": True}, "runs": redacted}, separators=(",", ":"))
        output = io.StringIO(newline="")
        fields = ["run_id", "created_at", "status", "task_type", "model_id", "agent_id", "input_tokens", "output_tokens", "cached_tokens", "token_provenance", "duration_ms", "latency_provenance", "actual_cost", "actual_cost_currency", "actual_cost_provenance", "value_amount", "value_currency", "value_category", "value_provenance"]
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(redacted)
        return output.getvalue()

    async def apply_retention(self, session: AsyncSession, days: int, now: datetime | None = None) -> Dict[str, Any]:
        if not 1 <= days <= 3650:
            raise DomainError("validation_failed", message="Telemetry retention must be between 1 and 3650 days.")
        cutoff = (now or datetime.utcnow()) - timedelta(days=days)
        usage = await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.observed_at < cutoff))
        latency = await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.observed_at < cutoff))
        result = {"cutoff": cutoff.isoformat(), "usage_deleted": usage.rowcount or 0, "latency_deleted": latency.rowcount or 0, "runs_deleted": 0}
        await audit_service.append(session, action="telemetry.retention_applied", resource_type="telemetry", resource_id="observations", details={"actor": "local_system", **result})
        await session.commit()
        return result

    def _row(self, run: TaskRun) -> Dict[str, Any]:
        evidence = json.loads(run.financials_json or "{}")
        actual = evidence.get("actual_cost", {})
        value = evidence.get("value", {})
        return {"run_id": run.id, "created_at": run.created_at.isoformat() if run.created_at else None, "status": run.status, "task_type": run.task_type, "model_id": run.selected_model_id, "agent_id": run.selected_agent_id, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens, "cached_tokens": run.cached_tokens, "token_provenance": run.token_provenance, "duration_ms": run.duration_ms, "latency_provenance": run.latency_provenance, "actual_cost": actual.get("amount"), "actual_cost_currency": actual.get("currency"), "actual_cost_provenance": actual.get("provenance", "unknown"), "value_amount": value.get("amount"), "value_currency": value.get("currency"), "value_category": value.get("category"), "value_provenance": value.get("provenance", "unknown")}


telemetry_export_service = TelemetryExportService()
