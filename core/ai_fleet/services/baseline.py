from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ModelRecord, SystemSetting
from .audit import audit_service
from .pricing import PricingService


class BaselineService:
    def __init__(self, pricing: PricingService):
        self._pricing = pricing

    async def set(self, session: AsyncSession, model_id: str) -> ModelRecord:
        model = await session.get(ModelRecord, model_id)
        if not model or model.lifecycle_status != "active":
            raise DomainError("resource_not_found", message="Active baseline model was not found.")
        price = await self._pricing.resolve(session, model_id, datetime.utcnow())
        if not price:
            raise DomainError("resource_conflict", message="A current verified/provider-reported price is required before selecting a baseline.")
        await session.execute(update(ModelRecord).values(is_reference_baseline=False))
        model.is_reference_baseline = True
        setting = await session.get(SystemSetting, "reference_baseline_model")
        if setting:
            setting.value = model_id
        else:
            session.add(SystemSetting(key="reference_baseline_model", value=model_id, description="Priced reference baseline model"))
        await audit_service.append(session, action="model.baseline_set", resource_type="model", resource_id=model_id, details={"price_id": price.id})
        await session.commit()
        return model

    async def current(self, session: AsyncSession) -> Dict[str, Any]:
        setting = await session.get(SystemSetting, "reference_baseline_model")
        model = await session.get(ModelRecord, setting.value) if setting else None
        if not model:
            return {"available": False, "reason": "baseline_not_configured", "model": None, "price": None}
        price = await self._pricing.resolve(session, model.id, datetime.utcnow())
        if not price:
            return {"available": False, "reason": "baseline_price_unavailable", "model": model.to_dict(), "price": None}
        return {"available": True, "reason": "ready", "model": model.to_dict(), "price": price.to_dict()}


baseline_service = BaselineService(PricingService())
