import json
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..engine.process_manager import ProcessManager
from ..storage.models import OrchestrationCheckpointRecord, ProjectRecord, WorkspaceRecord
from .executor_capabilities import ExecutorCapabilityService
from .orchestration_tasks import OrchestrationTaskService
from .project_dispatcher import ProjectDispatcherService


class ProductionPathCertificationService:
    async def certify(self, session: AsyncSession, model_id: str, timeout_seconds: float = 300) -> dict:
        suffix = uuid.uuid4().hex[:12]
        project_id = f"cert-project-{suffix}"
        workspace_id = f"cert-workspace-{suffix}"
        checkpoint_id = f"cert-checkpoint-{suffix}"
        with tempfile.TemporaryDirectory(prefix="temm-production-cert-") as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"scripts": {"build": "node -e \"process.exit(0)\""}, "dependencies": {"alpha": "1.0.0", "beta": "1.0.0"}}), encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({"name": "cert", "lockfileVersion": 3, "packages": {"": {"dependencies": {"alpha": "1.0.0", "beta": "1.0.0"}}}}), encoding="utf-8")
            session.add(ProjectRecord(id=project_id, name="Production path certification", slug=f"production-cert-{suffix}", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=workspace_id, name="Production certification", path=str(root), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(OrchestrationCheckpointRecord(id=checkpoint_id, project_id=project_id, state="approved", cursor_json=json.dumps({"dispatch": {"workspace_id": workspace_id}}), ready_queue_json="[]", active_task_ids_json="[]", lock_keys_json="[]", revision=1))
            await session.commit()
            tasks = OrchestrationTaskService()
            create_task = await tasks.create(session, project_id, {
                "task_type": "implementation",
                "title": "Prove production dependency and multi-file write",
                "description": "Remove alpha and beta from package.json root dependencies. Synchronize package-lock.json root dependencies. Create temm-write-proof.txt containing exactly TEMM_REAL_WRITE_OK and temm-second-proof.txt containing exactly TEMM_MULTI_FILE_OK. Run npm run build. Modify no other files.",
                "acceptance": [
                    {"criterion_id": "cert:manifest", "description": "Manifest dependencies removed.", "evaluator": {"type": "json_root_dependencies_absent", "path": "package.json", "names": ["alpha", "beta"]}},
                    {"criterion_id": "cert:lock", "description": "Lock root synchronized.", "evaluator": {"type": "json_root_dependencies_absent", "path": "package-lock.json", "names": ["alpha", "beta"]}},
                    {"criterion_id": "cert:write", "description": "Primary proof created.", "evaluator": {"type": "file_exact_content", "path": "temm-write-proof.txt", "content": "TEMM_REAL_WRITE_OK"}},
                    {"criterion_id": "cert:multi", "description": "Second coordinated proof created.", "evaluator": {"type": "file_exact_content", "path": "temm-second-proof.txt", "content": "TEMM_MULTI_FILE_OK"}},
                    {"criterion_id": "cert:scope", "description": "Only approved files changed.", "evaluator": {"type": "changed_files_subset", "paths": ["package.json", "package-lock.json", "temm-write-proof.txt", "temm-second-proof.txt"]}},
                ],
                "context_refs": [],
                "executor_needs": {"capabilities": ["coding", "file_read", "file_write", "multi_file_edit", "dependency_management", "command_execution"], "certification_model_id": model_id},
            })
            first = await ProjectDispatcherService(ProcessManager()).dispatch_ready(session, project_id, workspace_id, checkpoint_id, token_limit=8000, timeout_seconds=timeout_seconds, max_tasks=1)
            first_result = first["dispatched"][0] if first.get("dispatched") else None
            edit_result = None
            if first_result and first_result.get("all_acceptance_satisfied"):
                edit_task = await tasks.create(session, project_id, {
                    "task_type": "implementation", "title": "Prove production file edit",
                    "description": "Modify only temm-write-proof.txt so it contains exactly TEMM_REAL_EDIT_OK.",
                    "acceptance": [
                        {"criterion_id": "cert:edit", "description": "Existing proof edited exactly.", "evaluator": {"type": "file_exact_content", "path": "temm-write-proof.txt", "content": "TEMM_REAL_EDIT_OK"}},
                        {"criterion_id": "cert:edit-scope", "description": "Only primary proof changed.", "evaluator": {"type": "changed_files_subset", "paths": ["temm-write-proof.txt"]}},
                    ], "context_refs": [], "executor_needs": {"capabilities": ["coding", "file_read", "file_write"], "certification_model_id": model_id},
                })
                checkpoint = await session.get(OrchestrationCheckpointRecord, checkpoint_id)
                checkpoint.state = "approved"
                await session.commit()
                second = await ProjectDispatcherService(ProcessManager()).dispatch_ready(session, project_id, workspace_id, checkpoint_id, token_limit=8000, timeout_seconds=timeout_seconds, max_tasks=1)
                edit_result = second["dispatched"][0] if second.get("dispatched") else None
            success = bool(first_result and first_result.get("all_acceptance_satisfied") and edit_result and edit_result.get("all_acceptance_satisfied"))
            evidence = {"production_contract": True, "project_id": project_id, "workspace_id": workspace_id, "workspace_path": str(root), "create_run_id": first_result.get("run_id") if first_result else None, "create_attempt_id": first_result.get("attempt_id") if first_result else None, "edit_run_id": edit_result.get("run_id") if edit_result else None, "edit_attempt_id": edit_result.get("attempt_id") if edit_result else None}
            await ExecutorCapabilityService().certify(session, model_id, {"coding": success, "file_read": success, "file_write": success, "multi_file_edit": success, "dependency_management": success, "command_execution": success}, evidence)
            return {"success": success, "model_id": model_id, "first_task_id": create_task.id, "first": first_result, "edit": edit_result, "evidence": evidence}


production_path_certification_service = ProductionPathCertificationService()
