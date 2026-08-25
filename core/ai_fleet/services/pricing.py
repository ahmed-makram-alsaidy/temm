import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ModelPriceRecord, ModelRecord
from .audit import audit_service


PRICE_PROVENANCE = {"verified", "provider_reported", "user_declared"}
PRICE_SOURCES = {"official", "provider", "user", "connector"}
CONFIDENCE = {"high", "medium", "low", "unknown"}


class PricingService:
    async def record(self, session: AsyncSession, model_id: str, values: Dict[str, Any]) -> ModelPriceRecord:
        model = await session.get(ModelRecord, model_id)
        if not model:
            raise DomainError("resource_not_found", message="Model was not found.")
        provenance = values["provenance"]
        source_type = values["source_type"]
        confidence = values.get("confidence", "unknown")
        currency = values.get("currency", "USD").upper()
        if provenance not in PRICE_PROVENANCE or source_type not in PRICE_SOURCES or confidence not in CONFIDENCE:
            raise DomainError("validation_failed", message="Pricing provenance metadata is invalid.")
        if len(currency) != 3 or not currency.isalpha():
            raise DomainError("validation_failed", message="Pricing currency must be a three-letter code.")
        dimensions = {key: values.get(key) for key in ["input_per_m", "output_per_m", "cache_per_m", "reasoning_per_m"]}
        if all(value is None for value in dimensions.values()) or any(value is not None and value < 0 for value in dimensions.values()):
            raise DomainError("validation_failed", message="At least one non-negative price dimension is required.")
        effective_from = values["effective_from"]
        effective_to = values.get("effective_to")
        if effective_to and effective_to <= effective_from:
            raise DomainError("validation_failed", message="Pricing effective_to must be after effective_from.")
        overlap_conditions = [
            ModelPriceRecord.model_id == model_id,
            ModelPriceRecord.currency == currency,
            or_(ModelPriceRecord.effective_to.is_(None), ModelPriceRecord.effective_to > effective_from),
        ]
        if effective_to is not None:
            overlap_conditions.append(ModelPriceRecord.effective_from < effective_to)
        overlap = (await session.execute(
            select(ModelPriceRecord.id).where(*overlap_conditions).limit(1)
        )).scalar_one_or_none()
        if overlap:
            raise DomainError("resource_conflict", message="Pricing period overlaps an existing record.")
        record = ModelPriceRecord(
            id=f"price-{uuid.uuid4().hex[:12]}",
            model_id=model_id,
            currency=currency,
            source_type=source_type,
            source_uri=values.get("source_uri", ""),
            provenance=provenance,
            confidence=confidence,
            effective_from=effective_from,
            effective_to=effective_to,
            **dimensions,
        )
        session.add(record)
        if effective_to is None and provenance in {"verified", "provider_reported"}:
            model.input_cost_per_m = record.input_per_m
            model.output_cost_per_m = record.output_per_m
            model.cache_cost_per_m = record.cache_per_m
            model.reasoning_cost_per_m = record.reasoning_per_m
            model.pricing_provenance = provenance
            model.pricing_currency = currency
            model.pricing_effective_at = effective_from
            model.revision = (model.revision or 0) + 1
        await audit_service.append(session, action="model.price_recorded", resource_type="model", resource_id=model_id, details={"actor": "local_system", "price_id": record.id, "currency": currency, "provenance": provenance, "effective_from": effective_from.isoformat(), "revision": model.revision})
        await session.commit()
        return record

    async def resolve(self, session: AsyncSession, model_id: str, at: datetime, currency: str = "USD", required_dimensions: Optional[set[str]] = None) -> Optional[ModelPriceRecord]:
        allowed_dimensions = {"input", "output", "cache", "reasoning"}
        required = required_dimensions or set()
        if not required.issubset(allowed_dimensions):
            raise DomainError("validation_failed", message="Required pricing dimensions are invalid.")
        conditions = [
            ModelPriceRecord.model_id == model_id,
            ModelPriceRecord.currency == currency.upper(),
            ModelPriceRecord.effective_from <= at,
            or_(ModelPriceRecord.effective_to.is_(None), ModelPriceRecord.effective_to > at),
            ModelPriceRecord.provenance.in_(["verified", "provider_reported"]),
        ]
        columns = {"input": ModelPriceRecord.input_per_m, "output": ModelPriceRecord.output_per_m, "cache": ModelPriceRecord.cache_per_m, "reasoning": ModelPriceRecord.reasoning_per_m}
        conditions.extend(columns[dimension].is_not(None) for dimension in required)
        return (await session.execute(
            select(ModelPriceRecord).where(*conditions).order_by(ModelPriceRecord.effective_from.desc()).limit(1)
        )).scalar_one_or_none()

    async def list(self, session: AsyncSession, model_id: str) -> list[ModelPriceRecord]:
        return (await session.execute(
            select(ModelPriceRecord).where(ModelPriceRecord.model_id == model_id).order_by(ModelPriceRecord.effective_from.desc())
        )).scalars().all()


pricing_service = PricingService()
