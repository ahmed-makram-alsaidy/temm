import json
from pathlib import Path
from typing import Any, Dict

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..filesystem import PathPolicyError, path_policy
from ..storage.models import WorkspaceRecord
from .benchmark_suites import BenchmarkSuiteService


MAX_PACK_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 12
MAX_SCALAR_LENGTH = 100000


class BenchmarkPackService:
    def __init__(self, suites: BenchmarkSuiteService):
        self._suites = suites

    async def import_payload(self, session: AsyncSession, payload: Dict[str, Any], source_uri: str, provenance: str = "marketplace"):
        self._validate_shape(payload)
        imported = json.loads(json.dumps(payload))
        imported["provenance"] = provenance
        imported["source_uri"] = source_uri
        for case in imported.get("cases", []):
            case["provenance"] = provenance
        return await self._suites.create_version(session, imported)

    async def import_file(self, session: AsyncSession, workspace_id: str, relative_path: str):
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not workspace:
            raise DomainError("resource_not_found", message="Approved workspace was not found.")
        try:
            file_path = path_policy.contained_file(workspace.path, Path(workspace.path) / relative_path)
        except PathPolicyError as exc:
            raise DomainError("validation_failed", message=str(exc)) from exc
        if file_path.suffix.lower() not in {".json", ".yaml", ".yml"} or file_path.stat().st_size > MAX_PACK_BYTES:
            raise DomainError("validation_failed", message="Benchmark pack type or size is invalid.")
        try:
            text = file_path.read_text(encoding="utf-8")
            payload = json.loads(text) if file_path.suffix.lower() == ".json" else yaml.safe_load(text)
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise DomainError("validation_failed", message="Benchmark pack could not be parsed.") from exc
        self._validate_shape(payload)
        payload["provenance"] = "imported"
        for case in payload.get("cases", []):
            case["provenance"] = "imported"
        return await self._suites.create_version(session, payload)

    async def export(self, session: AsyncSession, version_id: str, format: str) -> str:
        from ..storage.models import BenchmarkSuiteVersionRecord
        version = await session.get(BenchmarkSuiteVersionRecord, version_id)
        if not version or format not in {"json", "yaml"}:
            raise DomainError("resource_not_found" if not version else "validation_failed", message="Benchmark version or export format is invalid.")
        cases = await self._suites.cases(session, version_id)
        payload: Dict[str, Any] = {"schema_version": "1.0", "suite_key": version.suite_key, "version": version.version, "name": version.name, "category": version.category, "description": version.description, "provenance": version.provenance, "source_uri": version.source_uri, "content_hash": version.content_hash, "cases": [{key: value for key, value in case.to_dict().items() if key not in {"id", "suite_version_id", "created_at"}} for case in cases]}
        return json.dumps(payload, indent=2) if format == "json" else yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

    def _validate_shape(self, value: Any, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise DomainError("validation_failed", message="Benchmark pack nesting is too deep.")
        if isinstance(value, dict):
            if len(value) > 10000 or any(not isinstance(key, str) or len(key) > 128 for key in value):
                raise DomainError("validation_failed", message="Benchmark pack object is invalid.")
            for item in value.values():
                self._validate_shape(item, depth + 1)
        elif isinstance(value, list):
            if len(value) > 10000:
                raise DomainError("validation_failed", message="Benchmark pack list is too large.")
            for item in value:
                self._validate_shape(item, depth + 1)
        elif isinstance(value, str) and len(value) > MAX_SCALAR_LENGTH:
            raise DomainError("validation_failed", message="Benchmark pack scalar is too large.")
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise DomainError("validation_failed", message="Benchmark pack contains an unsupported value.")
        if depth == 0 and not isinstance(value, dict):
            raise DomainError("validation_failed", message="Benchmark pack root must be an object.")


benchmark_pack_service = BenchmarkPackService(BenchmarkSuiteService())
