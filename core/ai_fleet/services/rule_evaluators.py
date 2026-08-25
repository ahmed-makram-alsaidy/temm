import json
import re
from typing import Any, Dict

from ..errors import DomainError


class RuleEvaluatorService:
    def evaluate(self, evaluator_type: str, output: str, config: Dict[str, Any], receipt: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if len(output.encode("utf-8")) > 2 * 1024 * 1024:
            raise DomainError("validation_failed", message="Evaluator output exceeds the 2 MiB limit.")
        if evaluator_type == "exact":
            expected = config.get("expected")
            if not isinstance(expected, str):
                raise DomainError("validation_failed", message="Exact evaluator requires expected text.")
            passed = output == expected
            evidence = {"expected_length": len(expected), "actual_length": len(output)}
        elif evaluator_type == "regex":
            pattern = config.get("pattern")
            if not isinstance(pattern, str) or len(pattern) > 1000:
                raise DomainError("validation_failed", message="Regex evaluator pattern is invalid.")
            try:
                passed = re.fullmatch(pattern, output, flags=re.DOTALL) is not None
            except re.error as exc:
                raise DomainError("validation_failed", message="Regex evaluator pattern is invalid.") from exc
            evidence = {"pattern": pattern, "match_mode": "fullmatch"}
        elif evaluator_type == "json_schema":
            try:
                value = json.loads(output)
            except json.JSONDecodeError:
                value = None
            schema = config.get("schema", config)
            passed = value is not None and self._schema(value, schema)
            evidence = {"schema": schema, "parsed": value is not None}
        elif evaluator_type in {"unit_test", "build", "lint", "type_check"}:
            if not receipt or "exit_code" not in receipt:
                raise DomainError("validation_failed", message="Command evaluator requires a persisted execution receipt.")
            passed = receipt.get("outcome") == "completed" and receipt.get("exit_code") == 0
            evidence = {"execution_id": receipt.get("task_id"), "outcome": receipt.get("outcome"), "exit_code": receipt.get("exit_code"), "error_code": receipt.get("error_code")}
        else:
            raise DomainError("validation_failed", message="Rule evaluator type is unsupported.")
        return {"evaluator_type": evaluator_type, "evaluator_version": "1.0", "passed": passed, "score": 100.0 if passed else 0.0, "provenance": "measured", "evidence": evidence}

    def _schema(self, value: Any, schema: Dict[str, Any]) -> bool:
        if not isinstance(schema, dict):
            return False
        types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool, "null": type(None)}
        expected = schema.get("type")
        if expected and (expected not in types or not isinstance(value, types[expected]) or expected in {"number", "integer"} and isinstance(value, bool)):
            return False
        if isinstance(value, dict):
            if any(key not in value for key in schema.get("required", [])):
                return False
            return all(key not in value or self._schema(value[key], child) for key, child in schema.get("properties", {}).items())
        if isinstance(value, list) and "items" in schema:
            return all(self._schema(item, schema["items"]) for item in value)
        return True


rule_evaluator_service = RuleEvaluatorService()
