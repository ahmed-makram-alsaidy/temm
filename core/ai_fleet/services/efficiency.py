import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

from ..storage.models import TaskRun


class EfficiencyService:
    def calculate(self, run: TaskRun, usage: Dict[str, Any]) -> Dict[str, Any]:
        result = {"run_id": run.id, "quality_per_1k_tokens": None, "quality_per_currency_unit": None, "exclusions": {}}
        if run.quality_eval_score is None or run.quality_provenance == "unknown":
            result["exclusions"]["quality"] = "quality_unavailable"
            return result
        quality = Decimal(str(run.quality_eval_score))
        token_values = usage.get("usage", {})
        token_sources = usage.get("provenance", {})
        required = ["input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]
        known = [key for key in required if token_values.get(key) is not None]
        if not known or any(token_sources.get(key) == "unknown" for key in known):
            result["exclusions"]["quality_per_1k_tokens"] = "token_evidence_unavailable"
        else:
            total = sum(int(token_values[key] or 0) for key in known)
            if total <= 0:
                result["exclusions"]["quality_per_1k_tokens"] = "zero_token_denominator"
            else:
                value = (quality * Decimal(1000) / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                result["quality_per_1k_tokens"] = {"value": str(value), "formula": "quality_score*1000/total_tokens", "quality_provenance": run.quality_provenance, "token_provenance": sorted(set(token_sources[key] for key in known)), "total_tokens": total}
        actual = json.loads(run.financials_json or "{}").get("actual_cost", {})
        if actual.get("amount") is None or actual.get("provenance") == "unknown":
            result["exclusions"]["quality_per_currency_unit"] = "cost_evidence_unavailable"
        elif Decimal(actual["amount"]) <= 0:
            result["exclusions"]["quality_per_currency_unit"] = "zero_cost_denominator"
        else:
            value = (quality / Decimal(actual["amount"])).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            result["quality_per_currency_unit"] = {"value": str(value), "formula": "quality_score/actual_cost", "quality_provenance": run.quality_provenance, "cost_provenance": actual["provenance"], "currency": actual["currency"], "actual_cost": actual["amount"]}
        return result


efficiency_service = EfficiencyService()
