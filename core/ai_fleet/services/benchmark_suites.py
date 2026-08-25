import hashlib
import json
import math
import re
import uuid
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import BenchmarkCaseRecord, BenchmarkSuiteVersionRecord
from .audit import audit_service


EVALUATORS = {"exact", "json_schema", "regex", "unit_test", "build", "lint", "type_check", "human", "model_judge"}
PROVENANCE = {"builtin", "user_authored", "imported", "community", "marketplace"}
DIFFICULTIES = {"easy", "medium", "hard", "expert"}


class BenchmarkSuiteService:
    async def create_version(self, session: AsyncSession, values: Dict[str, Any]) -> BenchmarkSuiteVersionRecord:
        suite_key = values["suite_key"].strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", suite_key) or values["provenance"] not in PROVENANCE:
            raise DomainError("validation_failed", message="Benchmark suite identity or provenance is invalid.")
        cases = self._cases(values["cases"])
        canonical = {"suite_key": suite_key, "name": values["name"].strip(), "category": values["category"].strip().lower(), "description": values.get("description", ""), "provenance": values["provenance"], "source_uri": values.get("source_uri", ""), "cases": cases}
        content_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = (await session.execute(select(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.content_hash == content_hash))).scalar_one_or_none()
        if existing:
            return existing
        version = int((await session.execute(select(func.max(BenchmarkSuiteVersionRecord.version)).where(BenchmarkSuiteVersionRecord.suite_key == suite_key))).scalar_one_or_none() or 0) + 1
        record = BenchmarkSuiteVersionRecord(id=f"suite-{uuid.uuid4().hex[:12]}", suite_key=suite_key, version=version, name=canonical["name"], category=canonical["category"], description=canonical["description"], provenance=canonical["provenance"], source_uri=canonical["source_uri"], content_hash=content_hash)
        session.add(record)
        await session.flush()
        for item in cases:
            case_values = dict(item)
            evaluator_config = case_values.pop("evaluator_config")
            session.add(BenchmarkCaseRecord(id=f"case-{uuid.uuid4().hex[:12]}", suite_version_id=record.id, evaluator_config=json.dumps(evaluator_config, sort_keys=True), **case_values))
        await audit_service.append(session, action="benchmark.version_created", resource_type="benchmark_suite", resource_id=suite_key, details={"actor": "local_system", "version": version, "content_hash": content_hash, "case_count": len(cases), "provenance": record.provenance})
        await session.commit()
        return record

    async def list_versions(self, session: AsyncSession, suite_key: str) -> List[BenchmarkSuiteVersionRecord]:
        return (await session.execute(select(BenchmarkSuiteVersionRecord).where(BenchmarkSuiteVersionRecord.suite_key == suite_key).order_by(BenchmarkSuiteVersionRecord.version.desc()))).scalars().all()

    async def cases(self, session: AsyncSession, version_id: str) -> List[BenchmarkCaseRecord]:
        return (await session.execute(select(BenchmarkCaseRecord).where(BenchmarkCaseRecord.suite_version_id == version_id).order_by(BenchmarkCaseRecord.case_key))).scalars().all()

    def _cases(self, values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not 1 <= len(values) <= 10000:
            raise DomainError("validation_failed", message="Benchmark suite must contain between one and 10,000 cases.")
        normalized = []
        keys = set()
        for value in values:
            key = value["case_key"].strip().lower()
            evaluator = value["evaluator_type"]
            difficulty = value.get("difficulty", "medium")
            weight = float(value.get("weight", 1.0))
            case_provenance = value.get("provenance", "user_authored")
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", key) or key in keys or evaluator not in EVALUATORS or difficulty not in DIFFICULTIES or case_provenance not in PROVENANCE or not math.isfinite(weight) or weight <= 0:
                raise DomainError("validation_failed", message="Benchmark case configuration is invalid.")
            if not value["prompt"].strip() or not value["expected_behavior"].strip():
                raise DomainError("validation_failed", message="Benchmark prompt and expected behavior are required.")
            keys.add(key)
            normalized.append({"case_key": key, "prompt": value["prompt"], "expected_behavior": value["expected_behavior"], "evaluator_type": evaluator, "evaluator_config": value.get("evaluator_config", {}), "category": value.get("category", "general").strip().lower(), "difficulty": difficulty, "weight": weight, "provenance": case_provenance})
        return sorted(normalized, key=lambda item: item["case_key"])


benchmark_suite_service = BenchmarkSuiteService()
