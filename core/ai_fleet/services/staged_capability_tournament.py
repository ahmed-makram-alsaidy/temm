"""Staged Capability Tournament for TEMM production-path route qualification.

Each stage is a separate minimal task dispatched through the canonical
ProjectDispatcherService lifecycle. Evidence is recorded per-stage per-route.
Failure in one stage does not prevent prior stages from contributing evidence.
"""

import json
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..engine.process_manager import ProcessManager
from ..storage.models import ModelRecord, OrchestrationCheckpointRecord, ProjectRecord, WorkspaceRecord
from .executor_capabilities import ExecutorCapabilityService
from .measurement import EXECUTOR_LOCAL_FAILURE
from .orchestration_tasks import OrchestrationTaskService
from .project_dispatcher import ProjectDispatcherService
from .execution_policy import executable_availability_ttl_seconds


STAGE_DEFINITIONS = [
    {
        "id": "file_write",
        "title": "File Write Probe",
        "description": "Create exactly one file named temm-write-proof.txt containing exactly TEMM_REAL_WRITE_OK. Do not create or modify any other file.",
        "acceptance": [
            {"criterion_id": "stage1:content", "description": "Proof file has exact content.", "evaluator": {"type": "file_exact_content", "path": "temm-write-proof.txt", "content": "TEMM_REAL_WRITE_OK"}},
            {"criterion_id": "stage1:scope", "description": "Only the proof file was created.", "evaluator": {"type": "changed_files_subset", "paths": ["temm-write-proof.txt"]}},
        ],
        "capabilities_demonstrated": ["coding", "file_read", "file_write"],
        "setup_files": {},
        "requires_prior": False,
    },
    {
        "id": "file_edit",
        "title": "File Edit Probe",
        "description": "Modify the existing file temm-write-proof.txt so its entire content is exactly TEMM_REAL_EDIT_OK. Do not create or modify any other file.",
        "acceptance": [
            {"criterion_id": "stage2:content", "description": "Proof file has edited content.", "evaluator": {"type": "file_exact_content", "path": "temm-write-proof.txt", "content": "TEMM_REAL_EDIT_OK"}},
            {"criterion_id": "stage2:scope", "description": "Only the proof file was modified.", "evaluator": {"type": "changed_files_subset", "paths": ["temm-write-proof.txt"]}},
        ],
        "capabilities_demonstrated": ["coding", "file_read", "file_write"],
        "setup_files": {"temm-write-proof.txt": "TEMM_REAL_WRITE_OK"},
        "requires_prior": True,
    },
    {
        "id": "multi_file_edit",
        "title": "Multi-File Edit Probe",
        "description": "Create exactly two files: temm-alpha.txt containing exactly ALPHA_CONTENT and temm-beta.txt containing exactly BETA_CONTENT. Do not create or modify any other file.",
        "acceptance": [
            {"criterion_id": "stage3:alpha", "description": "Alpha proof file has exact content.", "evaluator": {"type": "file_exact_content", "path": "temm-alpha.txt", "content": "ALPHA_CONTENT"}},
            {"criterion_id": "stage3:beta", "description": "Beta proof file has exact content.", "evaluator": {"type": "file_exact_content", "path": "temm-beta.txt", "content": "BETA_CONTENT"}},
            {"criterion_id": "stage3:scope", "description": "Only the two proof files were created.", "evaluator": {"type": "changed_files_subset", "paths": ["temm-alpha.txt", "temm-beta.txt"]}},
        ],
        "capabilities_demonstrated": ["coding", "file_write", "multi_file_edit"],
        "setup_files": {},
        "requires_prior": False,
    },
    {
        "id": "dependency_management",
        "title": "Dependency/Manifest Probe",
        "description": "Remove the dependency named remove-me from the root dependencies in package.json. Do not add any new dependencies. Do not create or modify any other file.",
        "acceptance": [
            {"criterion_id": "stage4:removed", "description": "Target dependency was removed.", "evaluator": {"type": "json_root_dependencies_absent", "path": "package.json", "names": ["remove-me"]}},
            {"criterion_id": "stage4:scope", "description": "Only package.json was modified.", "evaluator": {"type": "changed_files_subset", "paths": ["package.json"]}},
        ],
        "capabilities_demonstrated": ["coding", "file_read", "file_write", "dependency_management"],
        "setup_files": {"package.json": json.dumps({"name": "temm-dep-probe", "version": "1.0.0", "dependencies": {"keep-me": "1.0.0", "remove-me": "2.0.0"}}, indent=2)},
        "requires_prior": False,
    },
    {
        "id": "debugging",
        "title": "Debugging Probe",
        "description": "Repair the broken TypeScript file src/broken.ts so it contains valid TypeScript exporting the number 42. Do not create or modify any other file.",
        "acceptance": [
            {"criterion_id": "stage5:syntax", "description": "Broken artifact is repaired with valid TypeScript.", "evaluator": {"type": "file_contains_excludes", "path": "src/broken.ts", "contains": ["export", "42"], "excludes": ["TODO", "unfinished"]}},
            {"criterion_id": "stage5:scope", "description": "Only the broken artifact was modified.", "evaluator": {"type": "changed_files_subset", "paths": ["src/broken.ts"]}},
        ],
        "capabilities_demonstrated": ["coding", "file_read", "file_write", "debugging"],
        "setup_files": {"src/broken.ts": "export const value = (\n"},
        "requires_prior": False,
    },
]


class StagedCapabilityTournamentService:
    """Run independent staged probes through the full production dispatcher."""

    async def _promote_verified_route(self, session: AsyncSession, model_id: str, tournament_id: str) -> bool:
        """Make a fully passing production-path route temporarily executable."""
        model = await session.get(ModelRecord, model_id)
        if not model:
            return False
        now = datetime.utcnow()
        model.availability_state = "available"
        model.availability_checked_at = now
        model.availability_expires_at = now + timedelta(seconds=executable_availability_ttl_seconds())
        model.availability_evidence = json.dumps({
            "source": "production_path_tournament",
            "tournament_id": tournament_id,
        })
        model.revision = (model.revision or 0) + 1
        await session.commit()
        return True

    async def run_tournament(
        self,
        session: AsyncSession,
        model_id: str,
        timeout_per_stage: float = 120,
        stages: list[str] | None = None,
        exploration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute staged probes for one model route.

        Returns per-stage results and aggregated capability evidence. When the probe
        was triggered by exploration - a dispatch yielding renewal of a chronically
        failing route to measure this never-measured one - `exploration` carries why
        and on what production evidence, and is persisted onto this route's capability
        evidence so the decision that measured it is auditable from the route itself.
        """
        suffix = uuid.uuid4().hex[:12]
        project_id = f"tournament-project-{suffix}"
        workspace_id = f"tournament-workspace-{suffix}"
        checkpoint_id = f"tournament-checkpoint-{suffix}"

        results: list[dict] = []
        capabilities_proven: dict[str, bool] = {}
        selected_stages = [s for s in STAGE_DEFINITIONS if not stages or s["id"] in stages]

        with tempfile.TemporaryDirectory(prefix="temm-tournament-") as directory:
            root = Path(directory)

            # Register project infrastructure
            session.add(ProjectRecord(
                id=project_id, name=f"Capability Tournament {suffix}",
                slug=f"tournament-{suffix}", project_type="software", owner="local",
            ))
            session.add(WorkspaceRecord(
                id=workspace_id, name="Tournament workspace",
                path=str(root), permission_profile="developer",
                allowed_shells='["powershell"]',
            ))
            session.add(OrchestrationCheckpointRecord(
                id=checkpoint_id, project_id=project_id, state="approved",
                cursor_json=json.dumps({"dispatch": {"workspace_id": workspace_id}}),
                ready_queue_json="[]", active_task_ids_json="[]",
                lock_keys_json="[]", revision=1,
            ))
            await session.commit()

            manager = ProcessManager()

            for stage in selected_stages:
                # Prepare workspace for this stage
                for filename, content in stage["setup_files"].items():
                    target = root / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")

                # If stage requires output of a prior stage that didn't pass, skip
                if stage["requires_prior"] and results and not results[-1].get("passed"):
                    results.append({
                        "stage_id": stage["id"],
                        "passed": False,
                        "skipped": True,
                        "reason": "prior_stage_failed",
                    })
                    continue

                # Create minimal task
                task = await OrchestrationTaskService().create(session, project_id, {
                    "task_type": "implementation",
                    "title": stage["title"],
                    "description": stage["description"],
                    "acceptance": stage["acceptance"],
                    "context_refs": [],
                    "executor_needs": {
                        "capabilities": stage["capabilities_demonstrated"],
                        "certification_model_id": model_id,
                    },
                })

                # Reset checkpoint to approved for each stage dispatch
                checkpoint = await session.get(OrchestrationCheckpointRecord, checkpoint_id)
                checkpoint.state = "approved"
                checkpoint.revision += 1
                await session.commit()

                # Dispatch through canonical production path
                try:
                    dispatch_result = await ProjectDispatcherService(manager).dispatch_ready(
                        session, project_id, workspace_id, checkpoint_id,
                        token_limit=4000, timeout_seconds=timeout_per_stage, max_tasks=1,
                    )
                except Exception as exc:
                    # TEMM could not get the stage dispatched at all, so the route
                    # was never asked to do anything. Nothing about it is recorded:
                    # the same reasoning the measurement classification applies
                    # below to an attempt that did run.
                    results.append({
                        "stage_id": stage["id"],
                        "passed": False,
                        "error": str(exc),
                        "task_id": task.id,
                        "unmeasured": True,
                        "measurement_classification": EXECUTOR_LOCAL_FAILURE,
                        "measurement_reason": "stage_dispatch_raised",
                    })
                    break

                dispatched = dispatch_result.get("dispatched", [])
                if not dispatched:
                    results.append({
                        "stage_id": stage["id"],
                        "passed": False,
                        "error": "no_dispatch",
                        "task_id": task.id,
                        "unmeasured": True,
                        "measurement_classification": EXECUTOR_LOCAL_FAILURE,
                        "measurement_reason": "stage_not_dispatched",
                    })
                    break

                attempt_result = dispatched[0]
                passed = bool(attempt_result.get("all_acceptance_satisfied"))
                receipt = attempt_result.get("receipt") or {}
                # A provider that would not serve the request produced no measurement
                # of the route. Every other failing stage is evidence - that is what a
                # probe is for - but this one exercised nothing, and recording it as
                # incapacity is worse than merely wrong: renewal admits only routes
                # whose latest execution evidence is positive throughout, so one
                # refusal withdraws a proven route from renewal permanently, and the
                # allowance returning cannot bring it back. Production evidence
                # 2026-08-19: `aliyun/qwen3-coder-next` answered HTTP 403
                # `insufficient_quota` in 4.8s and was recorded as unable to code,
                # read files, or write files - about a run in which it was never
                # asked to do any of them.
                refusal = receipt.get("provider_refusal")
                # A refusal is only the case the provider announces. The rest of the
                # non-measurements announce nothing: the CLI exits non-zero with an
                # opaque error whether it failed to resolve the provider, was
                # rejected by it, or got back a body it could not parse - and TEMM
                # read all of them as the route's answer to the probe. Production
                # evidence 2026-08-20, `run-133922d95108`: the probed provider was
                # declared only in a config the isolated stage workspace could not
                # see, the CLI exited 1 in 1.9s without invoking the model, and the
                # route was recorded as unable to code, read files or write files.
                # Incapacity is admissible only where the model demonstrably did the
                # work and the work fell short - never where it was never asked.
                measurement = attempt_result.get("measurement") or receipt.get("measurement") or {}
                measured = bool(measurement.get("measured"))
                stage_result = {
                    "stage_id": stage["id"],
                    "passed": passed,
                    "task_id": attempt_result.get("task_id"),
                    "run_id": attempt_result.get("run_id"),
                    "attempt_id": attempt_result.get("attempt_id"),
                    "status": attempt_result.get("status"),
                    "acceptance": attempt_result.get("acceptance"),
                    "workspace_diff": attempt_result.get("workspace_diff"),
                    "no_effect": attempt_result.get("no_effect"),
                    "measurement": {
                        key: measurement.get(key)
                        for key in ("classification", "reason", "resolution_reached", "execution_proof", "error_events")
                    } if measurement else None,
                    **({"provider_refusal": refusal} if refusal and not passed else {}),
                    **({} if passed or measured else {
                        "unmeasured": True,
                        "measurement_classification": measurement.get("classification"),
                        "measurement_reason": measurement.get("reason"),
                    }),
                }
                results.append(stage_result)

                if passed:
                    for cap in stage["capabilities_demonstrated"]:
                        capabilities_proven[cap] = True
                elif not measured:
                    # Leave the capabilities unspoken for: absent from both the
                    # positive and the negative set, so the route keeps whatever its
                    # last real measurement said. What actually stopped the stage is
                    # already recorded on the attempt - a refusal excludes the route
                    # from selection while it stands, and a local or provider-side
                    # failure marks the route unexecutable on a short TTL - and those
                    # are the mechanisms sized to those facts.
                    break
                else:
                    # The model did the work and the work fell short. This is the one
                    # case a probe exists to record.
                    for cap in stage["capabilities_demonstrated"]:
                        capabilities_proven.setdefault(cap, False)
                    # Fail fast: stop testing this route
                    break

        # Persist capability evidence
        positive_caps = {cap for cap, proven in capabilities_proven.items() if proven}
        negative_caps = {cap for cap, proven in capabilities_proven.items() if not proven}

        all_selected_stages_passed = sum(1 for r in results if r.get("passed")) == len(selected_stages)
        # If all 4 AI stages passed, the model demonstrated tool invocation which
        # encompasses command execution through the same agent tool-calling interface.
        #
        # That inference needs the whole sweep, not merely everything a caller asked
        # for. `stages` narrows the run - a targeted re-verification takes one stage -
        # and a subset that passes proves only the capabilities its stages
        # demonstrate, so counting against the selection alone minted execution
        # evidence for a capability no probe in that run exercised.
        if all_selected_stages_passed and len(selected_stages) == len(STAGE_DEFINITIONS):
            positive_caps.add("command_execution")
            capabilities_proven["command_execution"] = True

        evidence_payload = {
            "tournament_id": suffix,
            "project_id": project_id,
            "stages_attempted": len(results),
            "stages_passed": sum(1 for r in results if r.get("passed")),
            "production_contract": True,
            "staged": True,
        }
        if exploration is not None:
            # The reason this route was measured at all, carried onto its evidence so
            # the chronic-failure-to-exploration decision is auditable from the route.
            evidence_payload["exploration"] = exploration

        # Add run/attempt IDs from results
        for result in results:
            if result.get("run_id"):
                evidence_payload[f"{result['stage_id']}_run_id"] = result["run_id"]
                evidence_payload[f"{result['stage_id']}_attempt_id"] = result.get("attempt_id")

        observations = {}
        for cap in positive_caps:
            observations[cap] = True
        for cap in negative_caps:
            observations[cap] = False

        await ExecutorCapabilityService().certify(session, model_id, observations, evidence_payload)
        if all_selected_stages_passed:
            # Availability is a statement about right now: every stage this run
            # selected drove the production dispatch path and satisfied its
            # acceptance, so the route is executable whether the run was a full
            # sweep or a narrower renewal.
            await self._promote_verified_route(session, model_id, suffix)

        return {
            "model_id": model_id,
            "tournament_id": suffix,
            "project_id": project_id,
            "stages": results,
            "capabilities_proven": capabilities_proven,
            "positive_capabilities": sorted(positive_caps),
            "negative_capabilities": sorted(negative_caps),
            "all_required_for_child_a": positive_caps >= {"coding", "file_read", "file_write", "multi_file_edit", "dependency_management", "command_execution"},
            "evidence": evidence_payload,
        }

    async def run_command_probe(
        self,
        session: AsyncSession,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Stage 5: Deterministic command execution through dispatch_command path.

        This does not require an AI model - it tests TEMM's own command execution.
        """
        suffix = uuid.uuid4().hex[:12]
        project_id = f"cmd-probe-project-{suffix}"
        workspace_id = f"cmd-probe-workspace-{suffix}"
        checkpoint_id = f"cmd-probe-checkpoint-{suffix}"

        with tempfile.TemporaryDirectory(prefix="temm-cmd-probe-") as directory:
            root = Path(directory)
            # Create a simple script that writes a proof file
            (root / "package.json").write_text(json.dumps({
                "name": "cmd-probe",
                "scripts": {"verify": "node -e \"require('fs').writeFileSync('cmd-proof.txt','CMD_OK')\""},
            }), encoding="utf-8")

            session.add(ProjectRecord(
                id=project_id, name=f"Command Probe {suffix}",
                slug=f"cmd-probe-{suffix}", project_type="software", owner="local",
            ))
            session.add(WorkspaceRecord(
                id=workspace_id, name="Command probe workspace",
                path=str(root), permission_profile="developer",
                allowed_shells='["powershell"]',
            ))
            session.add(OrchestrationCheckpointRecord(
                id=checkpoint_id, project_id=project_id, state="approved",
                cursor_json=json.dumps({"dispatch": {"workspace_id": workspace_id}}),
                ready_queue_json="[]", active_task_ids_json="[]",
                lock_keys_json="[]", revision=1,
            ))
            await session.commit()

            task = await OrchestrationTaskService().create(session, project_id, {
                "task_type": "command",
                "title": "Deterministic command execution probe",
                "description": "npm.cmd run verify" if __import__("os").name == "nt" else "npm run verify",
                "acceptance": [
                    {"criterion_id": "cmd:exit", "description": "Command exited successfully.", "evaluator": {"type": "gate_passed", "kind": "command"}},
                ],
                "context_refs": [],
                "executor_needs": {},
            })

            manager = ProcessManager()
            try:
                dispatch_result = await ProjectDispatcherService(manager).dispatch_ready(
                    session, project_id, workspace_id, checkpoint_id,
                    token_limit=1000, timeout_seconds=timeout_seconds, max_tasks=1,
                )
            except Exception as exc:
                return {"passed": False, "error": str(exc), "task_id": task.id}

            dispatched = dispatch_result.get("dispatched", [])
            if not dispatched:
                return {"passed": False, "error": "no_dispatch", "task_id": task.id}

            attempt_result = dispatched[0]
            proof_path = root / "cmd-proof.txt"
            proof_verified = proof_path.is_file() and proof_path.read_text(encoding="utf-8") == "CMD_OK"

            return {
                "passed": attempt_result.get("status") == "completed" and proof_verified,
                "task_id": attempt_result.get("task_id"),
                "run_id": attempt_result.get("run_id"),
                "attempt_id": attempt_result.get("attempt_id"),
                "status": attempt_result.get("status"),
                "proof_verified": proof_verified,
                "project_id": project_id,
            }


staged_capability_tournament_service = StagedCapabilityTournamentService()
