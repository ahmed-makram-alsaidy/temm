import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..filesystem import PathPolicyError, path_policy
from ..storage.models import RunArtifactRecord, RunAttemptRecord, TaskRun, WorkspaceRecord


ARTIFACT_TYPES = {"created", "modified", "deleted", "report", "build", "document", "asset", "other"}


class RunArtifactService:
    async def register(self, session: AsyncSession, run_id: str, relative_path: str, artifact_type: str, attempt_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> RunArtifactRecord:
        run = await session.get(TaskRun, run_id)
        if not run or not run.workspace_id:
            raise DomainError("resource_not_found", message="Run with an approved workspace was not found.")
        workspace = await session.get(WorkspaceRecord, run.workspace_id)
        if not workspace:
            raise DomainError("resource_not_found", message="Run workspace was not found.")
        if artifact_type not in ARTIFACT_TYPES:
            raise DomainError("validation_failed", message="Artifact type is invalid.")
        if attempt_id:
            attempt = await session.get(RunAttemptRecord, attempt_id)
            if not attempt or attempt.run_id != run_id:
                raise DomainError("validation_failed", message="Artifact attempt does not belong to this run.")
        candidate = Path(workspace.path) / relative_path
        try:
            file_path = path_policy.contained_file(workspace.path, candidate)
        except PathPolicyError as exc:
            raise DomainError("validation_failed", message=str(exc)) from exc
        relative = file_path.relative_to(Path(workspace.path).resolve()).as_posix()
        digest = hashlib.sha256()
        size = 0
        with file_path.open("rb") as handle:
            while chunk := handle.read(65536):
                size += len(chunk)
                digest.update(chunk)
        safe_metadata = {key: value for key, value in (metadata or {}).items() if isinstance(key, str) and isinstance(value, (str, int, float, bool, type(None)))}
        safe_metadata.update({"size_bytes": size, "mime_type": mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"})
        record = RunArtifactRecord(
            id=f"artifact-{uuid.uuid4().hex[:12]}", run_id=run_id, attempt_id=attempt_id,
            artifact_type=artifact_type, path=relative, sha256=digest.hexdigest(), metadata_json=json.dumps(safe_metadata),
        )
        session.add(record)
        await session.commit()
        return record

    async def list(self, session: AsyncSession, run_id: str) -> List[RunArtifactRecord]:
        return (await session.execute(select(RunArtifactRecord).where(RunArtifactRecord.run_id == run_id).order_by(RunArtifactRecord.created_at.asc()))).scalars().all()


run_artifact_service = RunArtifactService()
