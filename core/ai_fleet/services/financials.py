from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from ..errors import DomainError
from ..storage.models import ModelPriceRecord


MONEY_QUANTUM = Decimal("0.00000001")
FORMULA_VERSION = "token-price-v1"


@dataclass(frozen=True)
class CostResult:
    amount: Optional[str]
    currency: Optional[str]
    provenance: str
    method: Optional[str]
    formula_version: Optional[str]
    price_record_id: Optional[str]
    dimensions: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SavingsResult:
    category: str
    amount: Optional[str]
    currency: Optional[str]
    provenance: str
    method: Optional[str]
    actual_cost: Optional[str]
    reference_cost: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CostCalculator:
    def provider_reported(self, amount: Any, currency: str, provider_receipt_id: str) -> CostResult:
        value = self._money(amount)
        if not provider_receipt_id:
            raise DomainError("validation_failed", message="Provider-reported cost requires a receipt identifier.")
        return CostResult(str(value), self._currency(currency), "provider_reported", "provider_receipt", None, None, {"provider_receipt_id": provider_receipt_id})

    def formula(self, usage: Dict[str, Optional[int]], price: ModelPriceRecord, usage_provenance: Dict[str, str]) -> CostResult:
        dimensions = {"input": ("input_tokens", "input_per_m"), "output": ("output_tokens", "output_per_m"), "cache": ("cached_tokens", "cache_per_m"), "reasoning": ("reasoning_tokens", "reasoning_per_m")}
        required = [name for name, (token_key, _) in dimensions.items() if (usage.get(token_key) or 0) > 0]
        if any(getattr(price, dimensions[name][1]) is None for name in required):
            return CostResult(None, price.currency, "unknown", None, None, price.id, {"reason": "price_dimension_unavailable", "required_dimensions": required})
        if any(usage_provenance.get(dimensions[name][0], "unknown") == "unknown" for name in required):
            return CostResult(None, price.currency, "unknown", None, None, price.id, {"reason": "usage_dimension_unavailable", "required_dimensions": required})
        amount = Decimal("0")
        evidence: Dict[str, Any] = {}
        sources = set()
        for name in required:
            token_key, price_key = dimensions[name]
            tokens = int(usage[token_key] or 0)
            rate = Decimal(str(getattr(price, price_key)))
            amount += Decimal(tokens) * rate / Decimal(1_000_000)
            sources.add(usage_provenance[token_key])
            evidence[name] = {"tokens": tokens, "price_per_million": str(rate), "usage_provenance": usage_provenance[token_key]}
        provenance = "estimated" if "estimated" in sources else "provider_reported" if price.provenance == "provider_reported" and sources == {"provider_reported"} else "estimated"
        return CostResult(str(amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)), price.currency, provenance, FORMULA_VERSION, FORMULA_VERSION, price.id, evidence)

    def _money(self, value: Any) -> Decimal:
        try:
            amount = Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        except Exception as exc:
            raise DomainError("validation_failed", message="Cost amount is invalid.") from exc
        if amount < 0:
            raise DomainError("validation_failed", message="Cost amount cannot be negative.")
        return amount

    def _currency(self, value: str) -> str:
        currency = value.upper()
        if len(currency) != 3 or not currency.isalpha():
            raise DomainError("validation_failed", message="Cost currency must be a three-letter code.")
        return currency


class SavingsCalculator:
    def compare(self, actual: CostResult, reference: CostResult, category: str) -> SavingsResult:
        allowed = {"direct_saving", "estimated_avoided_cost", "equivalent_api_value"}
        if category not in allowed:
            raise DomainError("validation_failed", message="Savings category is invalid.")
        if actual.amount is None or reference.amount is None or actual.currency != reference.currency:
            return SavingsResult(category, None, actual.currency or reference.currency, "unknown", None, actual.amount, reference.amount)
        difference = max(Decimal("0"), Decimal(reference.amount) - Decimal(actual.amount)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if category == "direct_saving" and (actual.provenance != "provider_reported" or reference.provenance != "provider_reported"):
            return SavingsResult(category, None, actual.currency, "unknown", None, actual.amount, reference.amount)
        provenance = "provider_reported" if category == "direct_saving" else "estimated"
        method = "provider_billed_difference" if category == "direct_saving" else "baseline_equivalent_difference" if category == "estimated_avoided_cost" else "subscription_usage_api_equivalent"
        return SavingsResult(category, str(difference), actual.currency, provenance, method, actual.amount, reference.amount)


cost_calculator = CostCalculator()
savings_calculator = SavingsCalculator()
