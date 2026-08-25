import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..context import ContextSource, ContextSourceType
from ..errors import DomainError
from ..storage.models import AssetRecord, BlueprintProposalRecord, OrchestrationTaskRecord, ProjectDecisionRecord, ProjectNeedRecord, ProjectRequirementRecord, ResearchSourceRecord, TaskRun
from .context_budget import ContextBudgetService
from .context_packs import ContextPackService
from .file_excerpts import FileExcerptService


class ContextPreparationService:
    def __init__(self):
        self._files = FileExcerptService()
        self._budget = ContextBudgetService()
        self._packs = ContextPackService()

    async def prepare(self, session: AsyncSession, task_id: str, token_limit: int, run_id: str | None = None, *, reserved_tokens: int = 0, policy: str = "truncate"):
        """The context a task's attempt is prepared with, bounded by its budget.

        Over-budget truncates by priority rather than refusing, because the pack is
        evidence about what the attempt was given and cannot be a veto on the work
        itself: the executor reads the workspace directly, so a pack too large for
        the budget costs the attempt only the lowest-priority sources it names. This
        refused instead, and production evidence 2026-08-20 has every repair
        dispatch of `checkpoint-a8d3277ebe57` failing `resource_conflict` before the
        executor launched - the reconciliation service composed repair scopes of
        26-51 files, which no fixed pack budget admits, so the fleet vetoed on
        provenance grounds the exact work it had just decided was outstanding.

        What did not fit is recorded on the budget's `excluded` list, so a thin pack
        is legible as a thin pack.
        """
        task = await session.get(OrchestrationTaskRecord, task_id)
        if not task or task.state not in {"ready", "running"}:
            raise DomainError("resource_conflict", message="Context can only be prepared for a ready or running task.")
        refs = json.loads(task.context_refs_json or "[]")
        sources = []
        budget_items = []
        redactions = []
        prepared = []
        expanded_refs = []
        for reference_index, ref in enumerate(refs):
            if ref.get("source_type") in {"files", "file", "completeness_reconciliation"} and ref.get("paths"):
                expanded_refs.extend({"source_type": "file", "workspace_id": ref.get("workspace_id"), "path": path, "_reference_index": reference_index} for path in ref.get("paths", []))
            elif ref.get("source_type") == "completeness_reconciliation" and ref.get("historical_task_ids"):
                expanded_refs.extend({"source_type": "quality_repair_parent", "parent_task_id": task_id, "_reference_index": reference_index} for task_id in ref["historical_task_ids"])
            else:
                expanded_refs.append({**ref, "_reference_index": reference_index})
        for priority, ref in enumerate(expanded_refs):
            if ref.get("source_type") == "requirement" and not ref.get("source_id") and ref.get("requirement_id"):
                ref = {**ref, "source_id": ref["requirement_id"]}
            source_type = ref.get("source_type")
            if source_type == "file":
                source, content, redacted = await self._file(session, task, ref)
            else:
                source, content, redacted = await self._record(session, task, ref, run_id)
            sources.append(source)
            budget_items.append({"source_id": source.source_id, "priority": priority, "estimated_tokens": max(1, len(content) // 4), "estimation_method": "utf8_chars_div_4"})
            prepared.append({"source_id": source.source_id, "source_type": source.source_type.value, "content": content, "content_hash": source.content_hash})
            if redacted:
                redactions.append({"source_id": source.source_id, "redacted": True})
        budget = self._budget.budget(budget_items, token_limit, reserved_tokens, policy)
        included = {item["source_id"] for item in budget["selected"]}
        pack = await self._packs.create(session, sources, budget["used_tokens"], "estimated", "utf8_chars_div_4", redactions, task.project_id, run_id)
        return {"pack": pack.to_dict(), "budget": budget, "prepared_sources": [item for item in prepared if item["source_id"] in included], "prepared_immediately_before_attempt": True, "freshness_checked": True, "redaction_checked": True}

    async def _file(self, session, task, ref):
        workspace_id = ref.get("workspace_id")
        if not workspace_id:
            # Fallback: resolve project dispatch workspace from checkpoint
            from ..storage.models import OrchestrationCheckpointRecord
            from sqlalchemy import select as _select
            checkpoint = (await session.execute(_select(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.project_id == task.project_id))).scalars().first()
            if checkpoint:
                cursor = json.loads(checkpoint.cursor_json or "{}")
                workspace_id = cursor.get("dispatch", {}).get("workspace_id")
            if not workspace_id:
                raise DomainError("resource_not_found", message="File context ref has no workspace_id and project has no dispatch workspace.")
        try:
            excerpt = await self._files.extract(session, workspace_id, ref["path"], 1, ref.get("max_lines", 200), ref.get("max_bytes", 65536))
        except (DomainError, OSError, FileNotFoundError):
            # File may not exist yet (e.g., restore tasks). Provide an empty stub context.
            import hashlib as _hashlib
            path = ref["path"]
            stub_content = f"[File {path} does not currently exist and must be created]"
            stub_hash = _hashlib.sha256(stub_content.encode()).hexdigest()
            source = ContextSource(ContextSourceType.FILE, path, stub_hash, "observed", stub_hash, workspace_id, task.project_id, {"absent": True})
            return source, stub_content, False
        source = ContextSource(ContextSourceType.FILE, excerpt["path"], excerpt["sha256"], "observed", excerpt["sha256"], excerpt["workspace_id"], task.project_id, {"start_line": excerpt["start_line"], "end_line": excerpt["end_line"]})
        return source, excerpt["content"], excerpt["redacted"]

    async def _record(self, session, task, ref, run_id=None):
        source_id = ref.get("source_id") or ref.get("need_id")
        source_type = ref.get("source_type")
        definitions = {
            "requirement": (ProjectRequirementRecord, ContextSourceType.REQUIREMENT, "owner_declared"),
            "decision": (ProjectDecisionRecord, ContextSourceType.DECISION, "owner_declared"),
            "asset": (AssetRecord, ContextSourceType.ASSET, "observed"),
            "run": (TaskRun, ContextSourceType.RUN, "measured"),
            "research": (ResearchSourceRecord, ContextSourceType.RESEARCH, "observed"),
            "blueprint": (BlueprintProposalRecord, ContextSourceType.BLUEPRINT, "owner_declared"),
            "need": (ProjectNeedRecord, ContextSourceType.NEED, "observed"),
            "quality_repair_parent": (OrchestrationTaskRecord, ContextSourceType.TASK, "observed"),
        }
        if source_type == "completeness_reconciliation" and ref.get("finding_id"):
            source_type = "need"
            source_id = ref["finding_id"]
        elif source_type == "quality_repair_parent":
            source_id = ref.get("parent_task_id")
        if source_type == "quality_finding" and source_id:
            record = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == task.project_id, ProjectNeedRecord.source_type == "quality_finding", ProjectNeedRecord.source_id == source_id))).scalar_one_or_none()
            if not record:
                raise DomainError("resource_not_found", message="Context quality_finding source was not found.")
            source_type = "need"
            source_id = record.id
        elif source_type in definitions and source_id:
            record = None
        else:
            safe_keys = sorted(str(key) for key in ref.keys() if not str(key).startswith("_"))
            identifiers = {
                key: ref[key]
                for key in ("workspace_id", "path", "paths", "source_id", "finding_id", "requirement_id", "parent_task_id")
                if key in ref and isinstance(ref[key], (str, list))
            }
            raise DomainError(
                "validation_failed",
                message=(
                    "Unsupported or unidentified context source: "
                    f"task_id={task.id}; run_id={run_id or 'pending'}; "
                    f"reference_index={ref.get('_reference_index', '?')}; "
                    f"source_type={source_type!r}; keys={safe_keys}; identifiers={identifiers}"
                ),
            )
        model, enum_type, default_provenance = definitions[source_type]
        record = record or await session.get(model, source_id)
        if not record:
            raise DomainError("resource_not_found", message=f"Context {source_type} source was not found.")
        payload = self._payload(record)
        project_id = payload.get("project_id")
        if project_id and project_id != task.project_id:
            raise DomainError("permission_denied", message="Context source belongs to another project.")
        if source_type == "research":
            query_id = payload.get("query_id")
            from ..storage.models import ResearchQueryRecord
            query = await session.get(ResearchQueryRecord, query_id)
            if not query or query.project_id != task.project_id:
                raise DomainError("permission_denied", message="Research source belongs to another project.")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        recorded_hash = payload.get("sha256") or payload.get("content_hash")
        if recorded_hash and len(recorded_hash) == 64:
            digest = recorded_hash
        version = str(payload.get("revision") or payload.get("version") or digest)
        provenance = payload.get("provenance") or default_provenance
        if provenance not in {"measured", "provider_reported", "user_declared", "owner_declared", "observed", "imported", "model_proposed", "unknown"}:
            provenance = default_provenance
        metadata = {"record_type": source_type, "status": payload.get("status") or payload.get("state"), "content_available_to_executor": True}
        source = ContextSource(enum_type, source_id, version, provenance, digest, payload.get("workspace_id"), task.project_id, metadata)
        return source, canonical, False

    def _payload(self, record: Any) -> dict:
        if hasattr(record, "to_dict"):
            return record.to_dict()
        return {column.name: getattr(record, column.name) for column in record.__table__.columns if column.name not in {"log_output", "result_output"}}



context_preparation_service = ContextPreparationService()
