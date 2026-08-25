from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import SystemSetting
from .audit import audit_service


SETTINGS_SCHEMA_VERSION = "1.0"
DEFAULTS = {
    "monthly_ai_budget": 100.0,
    "budget_alert_threshold": 80.0,
    "default_routing_strategy": "balanced",
    "hourly_productivity_value": 25.0,
    "economy_auto_switch": True,
    "telemetry_retention_days": 365,
    "community_leaderboard_consent": False,
}


class SettingsService:
    async def read(self, session: AsyncSession) -> Dict[str, Any]:
        records = {item.key: item.value for item in (await session.execute(select(SystemSetting))).scalars().all()}
        values = dict(DEFAULTS)
        for key in DEFAULTS:
            if key in records:
                values[key] = self._parse(key, records[key])
        return {"schema_version": SETTINGS_SCHEMA_VERSION, "settings": values}

    async def update(self, session: AsyncSession, changes: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise DomainError("validation_failed", message="Unknown settings were provided.", details={"keys": sorted(unknown)})
        normalized = {key: self._validate(key, value) for key, value in changes.items()}
        for key, value in normalized.items():
            record = await session.get(SystemSetting, key)
            serialized = self._serialize(value)
            if record:
                record.value = serialized
            else:
                session.add(SystemSetting(key=key, value=serialized, description="User configured setting"))
        await audit_service.append(session, action="settings.updated", resource_type="settings", resource_id="system", details={"keys": sorted(normalized)})
        await session.commit()
        return await self.read(session)

    def _validate(self, key: str, value: Any) -> Any:
        if key in {"monthly_ai_budget", "hourly_productivity_value"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1_000_000:
                raise DomainError("validation_failed", message=f"Invalid value for {key}.")
            return float(value)
        if key == "telemetry_retention_days":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3650:
                raise DomainError("validation_failed", message="Telemetry retention must be between 1 and 3650 days.")
            return value
        if key == "budget_alert_threshold":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= float(value) <= 100:
                raise DomainError("validation_failed", message="Budget alert threshold must be between 1 and 100.")
            return float(value)
        if key == "default_routing_strategy":
            if value not in {"balanced", "economy", "quality", "fast"}:
                raise DomainError("validation_failed", message="Unsupported routing strategy.")
            return value
        if key in {"economy_auto_switch", "community_leaderboard_consent"}:
            if not isinstance(value, bool):
                raise DomainError("validation_failed", message=f"{key} must be boolean.")
            return value
        raise DomainError("validation_failed")

    def _parse(self, key: str, value: str) -> Any:
        try:
            if key in {"monthly_ai_budget", "budget_alert_threshold", "hourly_productivity_value"}:
                return self._validate(key, float(value))
            if key == "telemetry_retention_days":
                return self._validate(key, int(value))
            if key in {"economy_auto_switch", "community_leaderboard_consent"}:
                if value.lower() not in {"true", "false"}:
                    raise ValueError
                return value.lower() == "true"
            return self._validate(key, value)
        except (ValueError, DomainError):
            return DEFAULTS[key]

    def _serialize(self, value: Any) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)


settings_service = SettingsService()
