import hashlib
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..filesystem import PathPolicyError, path_policy
from ..security import SensitiveDataRedactor
from ..storage.models import WorkspaceRecord
from ..storage.secret_vault import secret_vault


class FileExcerptService:
    async def extract(self, session: AsyncSession, workspace_id: str, relative_path: str, start_line: int = 1, max_lines: int = 200, max_bytes: int = 65536) -> Dict[str, Any]:
        if start_line < 1 or not 1 <= max_lines <= 1000 or not 1 <= max_bytes <= 262144:
            raise DomainError("validation_failed", message="Excerpt bounds are invalid.")
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not workspace: raise DomainError("resource_not_found", message="Approved workspace was not found.")
        try: file_path = path_policy.contained_file(workspace.path, Path(workspace.path) / relative_path)
        except PathPolicyError as exc: raise DomainError("validation_failed", message=str(exc)) from exc
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024: raise DomainError("validation_failed", message="File exceeds the 10 MiB excerpt limit.")
        raw = file_path.read_bytes()
        if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")): raise DomainError("validation_failed", message="Binary files cannot be excerpted.")
        encoding = "utf-8"
        try: text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try: text = raw.decode("utf-16"); encoding = "utf-16"
            except UnicodeDecodeError as exc: raise DomainError("validation_failed", message="File encoding is unsupported.") from exc
        lines = text.splitlines(); selected = lines[start_line - 1:start_line - 1 + max_lines]
        excerpt = "\n".join(selected)
        encoded = excerpt.encode("utf-8")
        truncated_bytes = len(encoded) > max_bytes
        if truncated_bytes: excerpt = encoded[:max_bytes].decode("utf-8", errors="ignore")
        redacted = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact_text(excerpt)
        relative = file_path.relative_to(Path(workspace.path).resolve()).as_posix()
        return {"workspace_id": workspace_id, "path": relative, "start_line": start_line, "end_line": start_line + len(selected) - 1 if selected else start_line - 1, "content": redacted, "encoding": encoding, "file_size": size, "sha256": hashlib.sha256(raw).hexdigest(), "truncated_lines": start_line - 1 + max_lines < len(lines), "truncated_bytes": truncated_bytes, "redacted": redacted != excerpt}


file_excerpt_service = FileExcerptService()
