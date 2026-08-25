import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import BenchmarkSuiteVersionRecord, ModelRecord, TaskRun


class PersonalLeaderboardService:
    async def rank(self, session: AsyncSession, suite_version_id: str, category: Optional[str] = None, max_age_days: int = 365) -> Dict[str, Any]:
        if not 1 <= max_age_days <= 3650:
            raise DomainError("validation_failed", message="Leaderboard freshness window is invalid.")
        version = await session.get(BenchmarkSuiteVersionRecord, suite_version_id)
        if not version:
            raise DomainError("resource_not_found", message="Benchmark suite version was not found.")
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        runs = (await session.execute(select(TaskRun).where(TaskRun.status == "completed", TaskRun.quality_provenance == "measured", TaskRun.quality_eval_score.is_not(None), TaskRun.completed_at >= cutoff))).scalars().all()
        model_ids = {run.selected_model_id for run in runs if run.selected_model_id}
        models = (await session.execute(select(ModelRecord).where(ModelRecord.id.in_(model_ids), ModelRecord.lifecycle_status == "active"))).scalars().all() if model_ids else []
        owned = {model.id: model for model in models if model.source_type in {"user", "runtime", "connector"} or model.registry_state in {"configured", "discovered", "executable"}}
        grouped: Dict[str, List[TaskRun]] = defaultdict(list)
        for run in runs:
            metadata = json.loads(run.measurement_metadata or "{}")
            evidence = metadata.get("benchmark", {})
            if evidence.get("suite_version_id") != suite_version_id or evidence.get("content_hash") != version.content_hash or run.selected_model_id not in owned:
                continue
            if category and version.category != category:
                continue
            grouped[run.selected_model_id].append(run)
        rows = []
        for model_id, observations in grouped.items():
            score = sum(run.quality_eval_score for run in observations) / len(observations)
            latest = max(run.completed_at for run in observations)
            rows.append({"model_id": model_id, "model_name": owned[model_id].name, "score": round(score, 4), "sample_size": len(observations), "latest_observation_at": latest.isoformat(), "provenance": "measured", "suite_version_id": suite_version_id, "content_hash": version.content_hash, "category": version.category})
        rows.sort(key=lambda item: (-item["score"], -item["sample_size"], item["model_id"]))
        for index, row in enumerate(rows, start=1): row["rank"] = index
        return {"suite_version": version.to_dict(), "max_age_days": max_age_days, "rows": rows, "excluded_unknown_or_incomparable": len(runs) - sum(len(items) for items in grouped.values())}


personal_leaderboard_service = PersonalLeaderboardService()
