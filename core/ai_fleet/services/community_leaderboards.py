import uuid
from datetime import datetime, timezone

from ..errors import DomainError
from .leaderboards import personal_leaderboard_service
from .settings import settings_service


class CommunityLeaderboardService:
    async def consent(self, session, enabled: bool) -> dict:
        result = await settings_service.update(session, {"community_leaderboard_consent": enabled})
        return {"enabled": result["settings"]["community_leaderboard_consent"], "remote_revocation_claimed": False}

    async def preview(self, session, suite_version_id: str, max_age_days: int = 365) -> dict:
        ranked = await personal_leaderboard_service.rank(session, suite_version_id, None, max_age_days)
        rows = []
        for item in ranked["rows"]:
            observed = datetime.fromisoformat(item["latest_observation_at"])
            rows.append({
                "score_band": round(float(item["score"]) / 5) * 5,
                "sample_size_band": self._sample_band(int(item["sample_size"])),
                "observation_month": observed.strftime("%Y-%m"),
                "provenance": "measured",
            })
        return {
            "schema_version": "1.0",
            "suite_content_hash": ranked["suite_version"]["content_hash"],
            "category": ranked["suite_version"]["category"],
            "rows": rows,
            "excluded_fields": ["model_id", "model_name", "run_id", "prompt", "output", "workspace", "project", "provider_account", "exact_timestamp", "cost"],
            "upload_performed": False,
        }

    async def export(self, session, suite_version_id: str, max_age_days: int = 365) -> dict:
        settings = await settings_service.read(session)
        if not settings["settings"]["community_leaderboard_consent"]:
            raise DomainError("permission_denied", message="Community leaderboard sharing is disabled.")
        preview = await self.preview(session, suite_version_id, max_age_days)
        return {**preview, "export_id": f"community-export-{uuid.uuid4().hex}", "generated_at": datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()}

    def _sample_band(self, size: int) -> str:
        if size < 3:
            return "1-2"
        if size < 10:
            return "3-9"
        if size < 50:
            return "10-49"
        return "50+"


community_leaderboard_service = CommunityLeaderboardService()
