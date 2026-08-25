from typing import Any, Dict, List

from ..errors import DomainError


class ContextBudgetService:
    def budget(self, items: List[Dict[str, Any]], token_limit: int, reserved_tokens: int = 0, policy: str = "fail") -> Dict[str, Any]:
        if token_limit < 1 or reserved_tokens < 0 or reserved_tokens >= token_limit or policy not in {"fail", "truncate"}: raise DomainError("validation_failed", message="Context token budget is invalid.")
        available = token_limit - reserved_tokens; normalized = []
        for item in items:
            tokens = item.get("measured_tokens")
            provenance = "measured"
            method = None
            if tokens is None:
                tokens = item.get("estimated_tokens"); provenance = "estimated"; method = item.get("estimation_method")
                if tokens is not None and not method: raise DomainError("validation_failed", message="Estimated context tokens require a method.")
            if tokens is None or tokens < 0: raise DomainError("validation_failed", message="Context source token count is unavailable or invalid.")
            normalized.append({**item, "resolved_tokens": int(tokens), "token_provenance": provenance, "estimation_method": method})
        normalized.sort(key=lambda item: (item.get("priority", 9999), item.get("source_id", "")))
        total = sum(item["resolved_tokens"] for item in normalized)
        if total > available and policy == "fail": raise DomainError("resource_conflict", message="Context pack exceeds the model token budget.", details={"required_tokens": total, "available_tokens": available})
        selected=[]; excluded=[]; used=0
        for item in normalized:
            if used + item["resolved_tokens"] <= available: selected.append(item); used += item["resolved_tokens"]
            else: excluded.append({"source_id": item.get("source_id"), "tokens": item["resolved_tokens"], "reason": "token_budget_exceeded", "priority": item.get("priority")})
        # Truncation degrades a pack; it cannot manufacture one. A budget that cannot
        # admit even its highest-priority source is not a small budget, it is a
        # misconfigured one, and the caller has to hear that rather than receive an
        # empty pack described as prepared.
        if normalized and not selected: raise DomainError("resource_conflict", message="Context token budget admits no source.", details={"required_tokens": normalized[0]["resolved_tokens"], "available_tokens": available})
        return {"selected": selected, "excluded": excluded, "token_limit": token_limit, "reserved_tokens": reserved_tokens, "available_tokens": available, "used_tokens": used, "remaining_tokens": available-used, "policy": policy, "truncated": bool(excluded), "budgeter_version": "1.0"}


context_budget_service=ContextBudgetService()
