import ast
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import (
    OrchestrationCheckpointRecord,
    OrchestrationTaskRecord,
    ProjectNeedRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    RunAttemptRecord,
    TaskRun,
    WorkspaceRecord,
)
from .completion_assessment import CompletionAssessmentService
from .requirements import RequirementService
from .task_graph import TaskGraphService
from .workspace_acceptance import WorkspaceAcceptanceService


TERMINAL_TASK_STATES = {"completed", "cancelled"}
LIVE_TASK_STATES = {"planned", "ready", "running"}
RETIREABLE_TASK_STATES = {"planned", "ready"}
SURFACE_PROJECT_TYPES = {"business_system", "software", "website"}
SURFACE_TERMS = {"browser", "frontend", "ui", "user interface", "application shell", "dashboard", "responsive"}
IGNORED_PARTS = {".git", ".mypy_cache", ".ruff_cache", "__pycache__", "dist", "node_modules"}

# A repair chain is anchored to the task that originally failed, so a failing
# repair produces another attempt at the same work rather than a deeper
# "Repair incomplete work: Repair incomplete work: ..." task. This caps how many
# times that anchor may be retried before the finding is left for a different
# strategy instead of cloning tasks forever.
MAX_REPAIR_GENERATIONS = 3


class CompletenessReconciliationService:
    async def reconcile(
        self,
        session: AsyncSession,
        project_id: str,
        workspace_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        project = await session.get(ProjectRecord, project_id)
        workspace = await session.get(WorkspaceRecord, workspace_id)
        checkpoint = await session.get(OrchestrationCheckpointRecord, checkpoint_id)
        if not project or not workspace or not checkpoint or checkpoint.project_id != project_id:
            raise DomainError("resource_not_found", message="Project, workspace, or checkpoint was not found.")
        if checkpoint.state not in {"approved", "running"}:
            raise DomainError("resource_conflict", message="Completeness reconciliation requires an approved or running checkpoint.")

        root = Path(workspace.path)
        if not root.is_dir():
            raise DomainError("resource_not_found", message="Approved workspace path was not found.")

        requirements = (await session.execute(
            select(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == project_id)
        )).scalars().all()
        tasks = (await session.execute(
            select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id)
        )).scalars().all()

        created_findings: list[str] = []
        created_tasks: list[str] = []
        credited_requirements: list[str] = []
        resolved_findings: list[str] = []
        # The findings this pass observed, for the lapse check below. A finding type whose
        # condition the pass re-computes in full can be resolved by its own absence from
        # this set, which is the only route to resolution the two types that name no
        # requirement have.
        observed: dict[str, set[str]] = {"missing_deliverable_surface": set(), "broken_artifact": set()}
        # A task whose every criterion already passes against the untouched
        # workspace cannot prove that any work happened. Now that independent
        # acceptance decides completion, dispatching such a contract would record a
        # false completion, so retire it instead of offering it as executable work.
        created_findings.extend(await self._retire_unprovable(session, project_id, root, tasks))
        # Tasks created earlier in this pass must be visible to later duplicate
        # checks; reading only the pre-pass snapshot produced two live tasks for
        # the same requirement.
        live_tasks = list(tasks)
        task_index = {task.id: task for task in tasks}
        # Anchors whose repair was retired only because another live task covered the
        # same outstanding work stay open; see `_repair_capacity`.
        redundant = await self._redundant_retirements(session, project_id)

        for task in tasks:
            if task.state in TERMINAL_TASK_STATES or task.state not in {"failed", "blocked"}:
                continue
            attempt = await self._latest_attempt(session, task)
            receipt = json.loads(attempt.receipt_json or "{}") if attempt else {}
            changed_paths = [item.get("path") for item in receipt.get("workspace_diff", []) if item.get("path")]
            if changed_paths:
                origin = self._root_task(task, task_index)
                key = f"partial:{origin.id}"
                if not self._repair_capacity(live_tasks, key, redundant):
                    continue
                # The repair must re-prove the acceptance the origin task never
                # satisfied. Preservation-only criteria are true the moment the
                # files exist, so a repair carrying just those could pass without
                # doing any of the requested work.
                scope_paths = list(dict.fromkeys([*changed_paths, *self._scope_paths(origin)]))
                outstanding = self._outstanding_criteria(origin, key)
                # A carried-forward reachability-bearing `deliverable_surface` can only
                # be satisfied by wiring the surface into a module already reachable
                # from an application entry point. When the interrupted attempt never
                # touched such a module - it created the surface file but left it
                # unimported - the scope above names only the surface itself and the
                # contract is unsatisfiable: reachability demands editing an import
                # ancestor the scope forbids. Widen the scope to the existing reachable
                # shell, the exact set of legitimate wiring points, so the executor can
                # establish reachability.
                # A carried `path_absent` criterion requires a file gone, and deleting a
                # file is a change to it, so a scope that does not name the path fails
                # the removal it demands. TEMM told attempt-0510cc86c1cf that
                # `__inspect_db.cjs`, `debug-db.js`, `seed.js` and `seed-data.js` must
                # not exist and, three lines later, not to modify anything outside 36
                # paths that excluded all four. The run left them in place, which is
                # the only reading of the contract that could pass its scope criterion.
                scope_paths = list(dict.fromkeys([*scope_paths, *self._reachability_scope(root, outstanding), *self._removal_scope(outstanding)]))
                # A requirement that spans several files is stated as one `all_of`
                # whose inner checks carry the paths, and `_scope_paths` above reads
                # only an evaluator's own `path`/`paths` keys - an `all_of` has
                # neither, so the paths its checks measure reach the scope through
                # nothing. The two widenings above are type-specific
                # (`deliverable_surface` wiring, `path_absent` removals) and cover no
                # other kind of check, while `changed_files_subset` permits a repair
                # only the paths its own list names. The repair is therefore refused
                # for editing the very files it is measured on.
                #
                # Production evidence 2026-08-22. task-5e3303d8e2e2, the repair minted
                # for task-b4afa6822e1f's RBAC requirement, was scoped to
                # `ACCEPTANCE_SUMMARY.md`, `backend/src/app.ts` and
                # `backend/src/tests/rbac.test.ts` - the three paths the interrupted
                # attempt happened to write - while its carried `all_of` measures
                # `requireRole` inside `backend/src/routes/customers.ts`,
                # `products.ts` and `orders.ts`. Recomputed over the same origin this
                # merge yields six paths, adding exactly those three route files. The
                # repair for one of three remaining requirements was unsatisfiable the
                # moment it was minted, at the rendered write boundary and at the
                # scope criterion alike.
                #
                # `measured_paths` is the walk that descends `checks`, and
                # `outstanding` already excludes scope criteria, so no permitted-write
                # list leaks in through it.
                scope_paths = list(dict.fromkeys([*scope_paths, *sorted(WorkspaceAcceptanceService().measured_paths(outstanding))]))
                # Preservation protects the paths acceptance measures, not every path
                # the interrupted attempt happened to write. Freezing all of them made
                # an interrupted attempt's incidental output mandatory forever, and a
                # near-miss filename mandatory along with it: attempt-a1f4dce3c08b was
                # refused by its provider after writing the whole customers screen to
                # `CustomerPage.tsx` while its own criteria measured
                # `CustomersPage.tsx`. The repair was told every changed path must
                # still be present when it stopped, so it could not move the screen to
                # the path it was judged on; it kept the misnamed file and re-exported
                # it from the contracted one in 57 characters, failing a 1500-character
                # surface criterion and leaving two files for one screen.
                #
                # A changed path that no criterion names is a starting point, not a
                # deliverable, and a repair may complete it, relocate it, or drop it.
                # Where a criterion does name the path, deleting it would regress work
                # the origin proved, so it stays preserved - and the merged scope still
                # admits every changed path, so relocation remains inside the boundary.
                measured_paths = self._criterion_paths(origin)
                preserved = [value for value in changed_paths if value in measured_paths]
                criteria = [
                    *([{"criterion_id": f"{key}:files", "description": "Measured files the interrupted attempt produced remain present.", "evaluator": {"type": "paths_exist", "paths": preserved}}] if preserved else []),
                    {"criterion_id": f"{key}:scope", "description": "Repair remains bounded to the interrupted attempt and the original task scope.", "evaluator": {"type": "changed_files_subset", "paths": scope_paths}},
                    *outstanding,
                ]
                if not self._is_provable(root, criteria):
                    # The origin left nothing verifiable to re-prove, so a repair
                    # would complete without doing the work. The requirement pass
                    # below reports the missing acceptance contract instead.
                    continue
                finding = await self._finding(
                    session, project_id, key, "partial_execution",
                    f"Incomplete generated changes for {origin.title}",
                    f"The previous {attempt.status} attempt preserved partial filesystem changes and did not satisfy acceptance.",
                    origin.id, self._first_requirement(origin),
                )
                repair = await self._task(
                    session, project_id, key, f"Repair incomplete work: {origin.title}",
                    self._repair_description(origin, receipt),
                    self._requirement_ids(origin),
                    criteria,
                    [{"source_type": "completeness_reconciliation", "dedupe_key": key, "finding_id": finding.id, "parent_task_id": task.id, "origin_task_id": origin.id, "workspace_id": workspace_id, "paths": scope_paths}],
                )
                self._append_created(finding, repair, created_findings, created_tasks)
                live_tasks.append(repair)

        for relative, error in self._broken_python(root):
            key = f"syntax:{relative}"
            observed["broken_artifact"].add(key)
            finding = await self._finding(
                session, project_id, key, "broken_artifact", f"Generated Python artifact does not parse: {relative}",
                error, relative, None,
            )
            repair = await self._task(
                session, project_id, key, f"Repair Python syntax: {relative}",
                f"Repair the incomplete generated Python artifact {relative}. Preserve valid existing behavior and modify only this file.",
                [],
                [
                    {"criterion_id": f"{key}:syntax", "description": "Python artifact parses successfully.", "evaluator": {"type": "python_syntax_valid", "path": relative}},
                    {"criterion_id": f"{key}:scope", "description": "Only the broken artifact is changed.", "evaluator": {"type": "changed_files_subset", "paths": [relative]}},
                ],
                [{"source_type": "completeness_reconciliation", "dedupe_key": key, "finding_id": finding.id, "workspace_id": workspace_id, "path": relative}],
            )
            self._append_created(finding, repair, created_findings, created_tasks)
            live_tasks.append(repair)

        unresolved = [item for item in requirements if item.status not in {"completed", "waived"}]
        corpus = " ".join(f"{item.title} {item.description}" for item in unresolved).lower()
        surface_required = project.project_type in SURFACE_PROJECT_TYPES and any(term in corpus for term in SURFACE_TERMS)
        surface_paths = self._surface_paths(root)
        surface_usable = self._surface_is_usable(root, surface_paths)
        if surface_required and not surface_usable:
            key = "surface:application"
            observed["missing_deliverable_surface"].add(key)
            finding = await self._finding(
                session, project_id, key, "missing_deliverable_surface", "Required application surface is incomplete",
                "Approved requirements call for a browser or user-interface surface, but the workspace has no usable application surface.",
                "workspace", None,
            )
            repair = await self._task(
                session, project_id, key, "Complete required application surface",
                "Build the usable application surface required by the approved requirements. Implement real navigation, forms, data-backed workflows, loading, empty, and error states; do not leave a static placeholder.",
                [item.id for item in unresolved if any(term in f"{item.title} {item.description}".lower() for term in SURFACE_TERMS)],
                [{"criterion_id": f"{key}:usable", "description": "A meaningful, non-placeholder application surface exists.", "evaluator": {"type": "deliverable_surface", "paths": self._expected_surface_paths(project.project_type), "surface_type": "frontend", "min_chars": 1000, "required_any": ["login", "dashboard", "navigation", "form", "fetch(", "api/"]}}],
                [{"source_type": "completeness_reconciliation", "dedupe_key": key, "finding_id": finding.id, "workspace_id": workspace_id, "paths": self._expected_surface_paths(project.project_type)}],
            )
            self._append_created(finding, repair, created_findings, created_tasks)
            live_tasks.append(repair)

        for requirement in unresolved:
            evaluators = self._typed_requirement_acceptance(requirement)
            # A contract every one of whose typed clauses passes is a contract that has
            # been met, and this is the pass that can say so: it holds the workspace and
            # it evaluates the requirement's own criteria rather than any one task's.
            proof = self._measured_satisfaction(root, evaluators)
            if proof is not None and await self._credit_requirement(session, requirement, proof, workspace_id, resolved_findings):
                credited_requirements.append(requirement.id)
                continue
            if self._has_live_task(live_tasks, requirement.id, evaluators, root):
                continue
            key = f"requirement:{requirement.id}"
            finding = await self._finding(
                session, project_id, key, "unresolved_requirement", f"Unmet requirement: {requirement.title}",
                requirement.description or "The requirement lacks completed acceptance evidence.", requirement.id, requirement.id,
            )
            if proof is not None:
                # Satisfied, and its status does not admit completion - a `draft`
                # requirement has not been approved and a `blocked` one is held by the
                # graph. The finding above is true, because the requirement is not
                # resolved. The report below would not be: this contract is verifiable
                # and it is met.
                continue
            if not evaluators:
                # Prose acceptance cannot be machine-checked, so there is no contract an
                # executor could satisfy. Report the gap rather than queueing work that
                # would be marked complete without implementing the requirement. The
                # previous fallback asked only for one file anywhere in the workspace,
                # which every attempt satisfied by definition.
                #
                # This used to be `not self._is_provable(...)`, which is false both for a
                # requirement with no typed clause and for one whose every typed clause
                # passes - opposite situations, and the second is the requirement being
                # finished. So the fleet's answer to proving a requirement was to record
                # that the requirement had no way of being proven. Production evidence on
                # project-23a514f0c426: five of ten requirements were on record as having
                # "no verifiable acceptance contract" while holding three, four, two, two
                # and three typed evaluators respectively, and the newest of the five was
                # filed at 2026-08-22 00:18:13, minutes after the defect #63 fix stopped
                # acceptance measuring substance in a re-export barrel. Making
                # `Customer management` provably satisfied is what caused TEMM to declare
                # it unprovable.
                finding = await self._finding(
                    session, project_id, f"contract:{requirement.id}", "missing_acceptance_contract",
                    f"Requirement has no verifiable acceptance contract: {requirement.title}",
                    "The requirement states acceptance in prose only, so completion cannot be proven mechanically. Attach typed acceptance criteria to this requirement before implementation is dispatched.",
                    requirement.id, requirement.id,
                )
                if getattr(finding, "_completeness_created", False) and finding.id not in created_findings:
                    created_findings.append(finding.id)
                continue
            repair = await self._task(
                session, project_id, key, f"Complete requirement: {requirement.title}",
                f"Complete the approved requirement '{requirement.title}': {requirement.description}. Verify the result against the persisted acceptance criteria and preserve existing valid work.",
                [requirement.id], evaluators,
                [{"source_type": "completeness_reconciliation", "dedupe_key": key, "finding_id": finding.id, "workspace_id": workspace_id}, {"source_type": "requirement", "source_id": requirement.id, "revision": requirement.revision}],
            )
            self._append_created(finding, repair, created_findings, created_tasks)
            live_tasks.append(repair)

        # Suppressing duplicate creation does not heal a graph that already holds
        # one, and this pass runs last so it sees everything queued above.
        created_findings.extend(await self._retire_redundant(session, project_id, root, live_tasks))

        await self._rewire_repaired_dependencies(session, project_id)

        # Last, so both read the graph this pass leaves behind rather than the one it
        # found: a requirement credited above is settled by the time these run.
        resolved_findings.extend(await self._resolve_settled_findings(session, project_id, requirements, [*tasks, *live_tasks]))
        for need_type, keys in observed.items():
            resolved_findings.extend(await self._resolve_lapsed(session, project_id, need_type, keys))

        await session.commit()
        graph = await TaskGraphService().derive(session, project_id)
        checkpoint.state = "approved" if graph["ready_queue"] else checkpoint.state
        checkpoint.ready_queue_json = json.dumps(graph["ready_queue"])
        checkpoint.active_task_ids_json = "[]"
        checkpoint.lock_keys_json = "[]"
        checkpoint.revision += 1
        checkpoint.updated_at = datetime.utcnow()
        await session.commit()

        assessment = await CompletionAssessmentService().assess(session, project_id)
        return {
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "status": "executable" if graph["ready_queue"] else "complete" if assessment["ready"] else "incomplete",
            "findings_created": created_findings,
            "tasks_created": created_tasks,
            "requirements_credited": credited_requirements,
            "findings_resolved": resolved_findings,
            "ready_queue": graph["ready_queue"],
            "assessment_ready": assessment["ready"],
            "blockers": assessment["blockers"],
        }

    async def retire_unprovable_queue(self, session: AsyncSession, project_id: str, workspace_id: str) -> list[str]:
        """Retire queued tasks whose acceptance already passes untouched.

        Dispatch calls this as well as reconciliation, because recovery can return a
        blocked task to the queue without any reconciliation pass in between. With
        acceptance authoritative for completion, dispatching a contract that already
        passes would record a completion for work that never happened.
        """
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not workspace:
            raise DomainError("resource_not_found", message="Workspace was not found.")
        root = Path(workspace.path)
        if not root.is_dir():
            raise DomainError("resource_not_found", message="Approved workspace path was not found.")
        tasks = (await session.execute(
            select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id)
        )).scalars().all()
        return await self._retire_unprovable(session, project_id, root, tasks)

    async def _retire_unprovable(
        self,
        session: AsyncSession,
        project_id: str,
        root: Path,
        tasks: list[OrchestrationTaskRecord],
    ) -> list[str]:
        """Cancel queued tasks whose acceptance is already satisfied untouched.

        Such a contract is unprovable: an executor that did nothing would satisfy it.
        Only queued work is retired, so failed history and in-flight work are left
        exactly as they are.
        """
        findings: list[str] = []
        retired: set[str] = set()
        for task in tasks:
            if task.state not in RETIREABLE_TASK_STATES or self._is_provable(root, json.loads(task.acceptance_json or "[]")):
                continue
            finding = await self._finding(
                session, project_id, f"unprovable:{task.id}", "unprovable_acceptance",
                f"Unprovable acceptance contract: {task.title}",
                "Every acceptance criterion on this queued task already passes against the untouched workspace, so completing it would prove no work. The task was retired and the underlying requirement needs a verifiable acceptance contract.",
                task.id, self._first_requirement(task),
            )
            task.state = "cancelled"
            task.revision += 1
            task.updated_at = datetime.utcnow()
            retired.add(task.id)
            if getattr(finding, "_completeness_created", False) and finding.id not in findings:
                findings.append(finding.id)
        if retired:
            self._release_dependents(tasks, retired)
        await session.flush()
        return findings

    async def _retire_redundant(
        self,
        session: AsyncSession,
        project_id: str,
        root: Path,
        tasks: list[OrchestrationTaskRecord],
    ) -> list[str]:
        """Cancel queued work whose outstanding contract another live task already carries.

        task-bb3439579748 and task-b727f1f403d0 were both queued for the same shell
        requirement, each rewriting App.tsx, so whichever ran second would undo the
        first and neither would be dispatched against the other's evidence.
        Reconciliation exists to leave the graph in a consistent executable state, so
        a duplicate it can detect must be retired rather than left dispatchable.

        Redundancy is measured on the criteria that still fail: one that already
        passes distinguishes nothing. The task asserting the most overall is kept, so
        retirement can never drop an assertion - a repair keeps its preservation and
        scope criteria, which the fresh requirement task does not carry, and a task
        with extra outstanding work of its own is never collapsed into a narrower one.

        Repairs are never retired. A repair is anchored to preserved partial work and
        `_repair_capacity` reads its cancellation as a decision never to retry that
        anchor, so retiring one here would silently close it. Every duplicate pair
        observed is a repair against a fresh requirement task, and two repairs for
        one anchor cannot coexist, so this costs no coverage.
        """
        findings: list[str] = []
        retired: set[str] = set()
        # `_task` returns the existing live task when a dedupe key already has one,
        # so the caller's list holds that record twice. Left in, the second entry
        # found the first as its own keeper and retired the task in favour of itself.
        live = list({task.id: task for task in tasks if task.state in LIVE_TASK_STATES}.values())
        outstanding = {task.id: self._outstanding_evaluators(root, task) for task in live}
        ranked = sorted(live, key=lambda task: (
            -len(json.loads(task.acceptance_json or "[]")), -len(outstanding[task.id]),
            task.created_at or datetime.min, task.id,
        ))
        for index in range(len(ranked) - 1, -1, -1):
            task = ranked[index]
            if task.state not in RETIREABLE_TASK_STATES or not outstanding[task.id] or self._is_repair(task):
                continue
            requirement_ids = set(self._requirement_ids(task))
            if not requirement_ids:
                continue
            keeper = next((
                other for other in ranked[:index]
                if other.id not in retired
                and requirement_ids & set(self._requirement_ids(other))
                and all(evaluator in outstanding[other.id] for evaluator in outstanding[task.id])
            ), None)
            if not keeper:
                continue
            finding = await self._finding(
                session, project_id, f"redundant:{task.id}", "redundant_live_task",
                f"Duplicate queued work: {task.title}",
                f"Every acceptance criterion this queued task still has to prove is also carried by live task {keeper.id} "
                f"({keeper.title}) for the same requirement. Two tasks rewriting the same surface would overwrite each "
                "other, so this one was retired and the broader contract was kept.",
                task.id, self._first_requirement(task),
            )
            task.state = "cancelled"
            task.revision += 1
            task.updated_at = datetime.utcnow()
            retired.add(task.id)
            if getattr(finding, "_completeness_created", False) and finding.id not in findings:
                findings.append(finding.id)
        if retired:
            self._release_dependents(tasks, retired)
        await session.flush()
        return findings

    async def _redundant_retirements(self, session: AsyncSession, project_id: str) -> set[str]:
        """Return the tasks this service retired for redundancy rather than by decision."""
        needs = (await session.execute(select(ProjectNeedRecord).where(
            ProjectNeedRecord.project_id == project_id, ProjectNeedRecord.need_type == "redundant_live_task",
        ))).scalars().all()
        return {need.source_id for need in needs if need.source_id}

    def _outstanding_evaluators(self, root: Path, task: OrchestrationTaskRecord) -> list[dict]:
        """Return the evaluators on this task that the workspace does not satisfy yet."""
        criteria = [item for item in json.loads(task.acceptance_json or "[]") if item.get("evaluator")]
        if not criteria:
            return []
        results = WorkspaceAcceptanceService().evaluate(root, criteria, [])
        return [item["evaluator"] for item, result in zip(criteria, results) if result["status"] != "passed"]

    def _release_dependents(self, tasks: list[OrchestrationTaskRecord], retired: set[str]) -> None:
        """Stop dependents waiting on retired work.

        The graph only releases a task once every dependency is completed, and a
        retired task never completes.
        """
        for task in tasks:
            dependencies = json.loads(task.dependency_ids_json or "[]")
            remaining = [item for item in dependencies if item not in retired]
            if remaining != dependencies:
                task.dependency_ids_json = json.dumps(remaining)
                task.revision += 1

    def _measured_satisfaction(self, root: Path, criteria: list[dict]) -> list[dict] | None:
        """Return the evaluation of a contract every clause of which passes, else None.

        `_is_provable` asks whether a contract can still prove work happened, which is
        the question a task asks before it is dispatched. This asks the opposite and
        distinct question a requirement asks: whether the work is already done. Both are
        false for a contract with no typed clause, which is why one cannot be written as
        the negation of the other - and reading it as one is defect #65.

        A clause is only ever `passed` or `failed`, so "none failed" and "all passed"
        coincide today; this states the condition it actually needs, so a third status
        could never be silently read as satisfaction.
        """
        if not criteria:
            return None
        results = WorkspaceAcceptanceService().evaluate(root, criteria, [])
        return results if results and all(item["status"] == "passed" for item in results) else None

    async def _credit_requirement(self, session: AsyncSession, requirement: ProjectRequirementRecord, proof: list[dict], workspace_id: str, resolved: list[str] | None = None) -> bool:
        """Record a measured requirement completion, and retire what it falsifies.

        The measurement is persisted as the requirement's evidence, which is what makes
        the transition legal under the same rule a human transition obeys. Nothing here
        interprets or summarises the result: the criterion ids and their statuses are
        the finding, and a bounded list of them is all that is written - no stdout, no
        file contents, no secrets.

        Two findings asserted something this measurement disproves, and resolving them
        is the evidence loop closing rather than a blocker being cleared: the
        requirement is no longer unresolved, and it demonstrably does have a verifiable
        acceptance contract. Every other blocking finding on the project is left exactly
        as it is - see the separate defect that no other finding has any writer of
        `resolved` at all.
        """
        evidence = {
            "source_type": "workspace_acceptance",
            "workspace_id": workspace_id,
            "measured_at": datetime.utcnow().isoformat(),
            "criteria": [{"criterion_id": item.get("criterion_id"), "status": item["status"]} for item in proof],
        }
        if not await RequirementService().record_measured_completion(session, requirement, evidence):
            return False
        closed = await self._resolve_findings(session, requirement, evidence, [f"requirement:{requirement.id}", f"contract:{requirement.id}"])
        if resolved is not None:
            resolved.extend(closed)
        return True

    async def _resolve_findings(self, session: AsyncSession, requirement: ProjectRequirementRecord, evidence: dict, keys: list[str]) -> list[str]:
        """Close the named findings against this requirement, keeping the measurement."""
        return await self._resolve_by_key(session, requirement.project_id, keys, evidence)

    async def _resolve_by_key(self, session: AsyncSession, project_id: str, keys: list[str], evidence: dict) -> list[str]:
        """Close the findings under these dedupe keys, keeping what disproved them."""
        resolved: list[str] = []
        records = (await session.execute(select(ProjectNeedRecord).where(
            ProjectNeedRecord.project_id == project_id,
            ProjectNeedRecord.dedupe_key.in_([f"completeness:{key}" for key in keys]),
        ))).scalars().all()
        for record in records:
            if record.state in {"resolved", "waived"}:
                continue
            record.state = "resolved"
            record.resolved_at = datetime.utcnow()
            record.resolution_json = json.dumps(evidence)
            resolved.append(record.id)
        await session.flush()
        return resolved

    async def _resolve_lapsed(self, session: AsyncSession, project_id: str, need_type: str, observed: set[str]) -> list[str]:
        """Retire the findings of this type whose premise this pass did not re-observe.

        `missing_deliverable_surface` and `broken_artifact` are the two findings filed
        with `requirement_id=None` - against the workspace and against a file - so
        requirement settlement can never reach them and before this they had no route to
        resolution at all. Either would have blocked delivery for the life of the project
        even once the surface it asks for existed or the file it names parsed.

        Both are filed from a condition this pass re-computes in full and unconditionally:
        `_surface_is_usable` over the workspace, and `_broken_python` over every Python
        file in it. So the pass's own silence is the measurement - a finding of one of
        these types that was not re-filed here is a finding whose premise no longer holds,
        and it stops blocking. That equivalence is why this may only be used for a type
        whose every filing site runs on every pass; a type filed conditionally would be
        resolved by the condition not being reached rather than by evidence.

        Resolution is not a latch: `_finding` reopens a resolved record the moment its
        condition recurs, so a surface that regresses or a file that stops parsing files
        the same finding again on the next pass.
        """
        records = (await session.execute(select(ProjectNeedRecord).where(
            ProjectNeedRecord.project_id == project_id,
            ProjectNeedRecord.source_type == "completeness_reconciliation",
            ProjectNeedRecord.need_type == need_type,
            ProjectNeedRecord.state.in_(["open", "in_progress"]),
        ))).scalars().all()
        resolved: list[str] = []
        for record in records:
            if record.dedupe_key in {f"completeness:{key}" for key in observed}:
                continue
            record.state = "resolved"
            record.resolved_at = datetime.utcnow()
            record.resolution_json = json.dumps({
                "reason": "premise_no_longer_observed",
                "need_type": need_type,
                "source_type": "completeness_reconciliation",
                "resolved_at": datetime.utcnow().isoformat(),
            })
            resolved.append(record.id)
        await session.flush()
        return resolved

    async def _resolve_settled_findings(
        self,
        session: AsyncSession,
        project_id: str,
        requirements: list[ProjectRequirementRecord],
        tasks: list[OrchestrationTaskRecord],
    ) -> list[str]:
        """Retire the findings whose requirement has since been settled.

        Defect #67: `_resolve_findings` was the only writer of `resolved` anywhere in the
        engine and it reached exactly two dedupe keys, both naming a requirement. Every
        other finding this service files - `partial_execution`, `unprovable_acceptance`,
        `redundant_live_task`, `missing_deliverable_surface` - had no path to resolution
        at all, and `CompletionAssessmentService.assess` blocks on every finding whose
        impact is blocking and whose state is `open` or `in_progress`. So delivery
        readiness stayed unreachable no matter how much work was proven, for the same
        structural reason as defect #65 and independently of it.

        Production evidence on project-23a514f0c426, 2026-08-22 02:17, taken immediately
        after the #65 fix credited five requirements on measured workspace acceptance:
        26 of the 61 open blocking findings named one of those five now-`completed`
        requirements - 12 `partial_execution`, 10 `unprovable_acceptance` and 4
        `redundant_live_task`, each asserting outstanding or duplicated work on a
        requirement TEMM had itself just proven satisfied.

        A settled requirement is the evidence. `completed` is only reachable from a
        measured contract or an explicit human transition, and `waived` only from a human
        one, so nothing here can retire a finding on anything but a recorded decision or
        a measurement. This is deliberately not a blocker sweep: a finding whose
        requirement is still open is untouched, findings from other sources are not this
        service's to close, and resolution is not permanent - `_finding` reopens a
        resolved record the moment its condition recurs, so the state tracks the
        workspace rather than latching.

        Outstanding work also cannot be hidden this way, because findings and tasks are
        separate blocker categories: a repair task with unmet criteria goes on blocking
        under `tasks` whatever happens to the finding that filed it.
        """
        settled = {item.id: item for item in requirements if item.status in {"completed", "waived"}}
        if not settled:
            return []
        by_id = {task.id: task for task in tasks}
        records = (await session.execute(select(ProjectNeedRecord).where(
            ProjectNeedRecord.project_id == project_id,
            ProjectNeedRecord.source_type == "completeness_reconciliation",
            ProjectNeedRecord.state.in_(["open", "in_progress"]),
        ))).scalars().all()
        resolved: list[str] = []
        for record in records:
            requirement = settled.get(record.requirement_id)
            if requirement is None:
                continue
            origin = by_id.get(record.source_id)
            if origin is not None and any(value not in settled for value in self._requirement_ids(origin)):
                # `requirement_id` holds only the first requirement its source task
                # names, so settling that one does not settle what the finding is about.
                # Every requirement the task carries has to be settled, or the finding
                # still has something true to say.
                continue
            record.state = "resolved"
            record.resolved_at = datetime.utcnow()
            record.resolution_json = json.dumps(self._settlement_evidence(requirement))
            resolved.append(record.id)
        await session.flush()
        return resolved

    def _settlement_evidence(self, requirement: ProjectRequirementRecord) -> dict:
        """The requirement's own settlement, recorded as the resolution of a finding.

        Carries the measurement that settled it rather than a restatement: the criterion
        ids and their statuses, bounded, with no stdout, no file contents and no secrets.
        A requirement settled by a human transition has no measurement to carry, and the
        status alone is then the whole of the evidence.
        """
        history = json.loads(requirement.evidence_json or "[]")
        latest = history[-1] if history else {}
        return {
            "reason": "requirement_settled",
            "requirement_id": requirement.id,
            "requirement_status": requirement.status,
            "resolved_at": datetime.utcnow().isoformat(),
            "measured_at": latest.get("measured_at"),
            "source_type": latest.get("source_type"),
            "criteria": (latest.get("criteria") or [])[:24],
        }

    def _is_provable(self, root: Path, criteria: list[dict]) -> bool:
        """Report whether a contract can still prove that work happened."""
        if not criteria:
            return False
        results = WorkspaceAcceptanceService().evaluate(root, criteria, [])
        return any(item["status"] == "failed" for item in results)

    async def _latest_attempt(self, session: AsyncSession, task: OrchestrationTaskRecord) -> RunAttemptRecord | None:
        if not task.current_run_id:
            return None
        return (await session.execute(
            select(RunAttemptRecord).where(RunAttemptRecord.run_id == task.current_run_id).order_by(RunAttemptRecord.attempt_number.desc())
        )).scalars().first()

    async def _finding(self, session, project_id, key, need_type, title, description, source_id, requirement_id):
        dedupe = f"completeness:{key}"
        existing = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == project_id, ProjectNeedRecord.dedupe_key == dedupe))).scalars().first()
        if existing:
            if existing.state in {"resolved", "waived"}:
                existing.state = "open"
                existing.resolved_at = None
                existing.resolution_json = None
            return existing
        record = ProjectNeedRecord(
            id=f"need-{uuid.uuid4().hex[:12]}", project_id=project_id, requirement_id=requirement_id,
            need_type=need_type, title=title, description=description, source_type="completeness_reconciliation",
            source_id=source_id, impact="blocking", blocked_nodes_json="[]", state="open", dedupe_key=dedupe,
        )
        session.add(record)
        await session.flush()
        record._completeness_created = True
        return record

    async def _task(self, session, project_id, key, title, description, requirement_ids, acceptance, context_refs):
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id))).scalars().all()
        for task in tasks:
            refs = json.loads(task.context_refs_json or "[]")
            if task.state in LIVE_TASK_STATES and any(ref.get("source_type") == "completeness_reconciliation" and ref.get("dedupe_key") == key for ref in refs):
                # A dedupe hit used to return the record untouched, which froze what
                # a task asks for at the moment it was first queued. Reconciliation
                # recomputes the description and the carried criteria on every pass
                # and threw that recomputation away, so a correction to how work is
                # stated could never reach work already waiting: defect #51 landed
                # and all three planned NEXA repairs still opened with the previous
                # attempt's process outcome, because each had been created hours
                # earlier.
                #
                # Restating is safe only before the contract has been measured. A
                # `planned` task that has never held a run is queued intent and
                # nothing else; once a task is `ready`, `running`, or carries a run,
                # an executor is reading these words or an attempt is already judged
                # against these criteria, and rewriting them mid-flight would move
                # the goalposts under evidence. Title, description and acceptance are
                # refreshed together because they are three renderings of one
                # computation - swapping the description alone could name a scope the
                # stored scope criterion does not measure.
                if task.state == "planned" and not task.current_run_id:
                    task.title = title
                    task.description = description
                    task.acceptance_json = json.dumps(acceptance)
                    # Identity and chain wiring outlive a restatement: the refs that
                    # record which generations came before are what
                    # `_rewire_repaired_dependencies` walks.
                    inherited = [ref for ref in refs if ref.get("source_type") == "quality_repair_parent"]
                    task.context_refs_json = json.dumps([*context_refs, *inherited])
                return task
        historical = [
            task.id for task in tasks
            if task.state in {"failed", "blocked", "completed"}
            and any(ref.get("source_type") == "completeness_reconciliation" and ref.get("dedupe_key") == key for ref in json.loads(task.context_refs_json or "[]"))
        ]
        if historical:
            context_refs = [*context_refs, *({"source_type": "quality_repair_parent", "parent_task_id": task_id} for task_id in historical)]
        record = OrchestrationTaskRecord(
            id=f"task-{uuid.uuid4().hex[:12]}", project_id=project_id, task_type="implementation",
            title=title, description=description, requirement_ids_json=json.dumps(requirement_ids), dependency_ids_json="[]",
            acceptance_json=json.dumps(acceptance), context_refs_json=json.dumps(context_refs),
            executor_needs_json=json.dumps({"capabilities": ["coding", "file_read", "file_write"]}), state="planned",
        )
        session.add(record)
        await session.flush()
        parent_ids = {ref.get("parent_task_id") for ref in context_refs if ref.get("parent_task_id")}
        if parent_ids:
            for dependent in tasks:
                dependency_ids = json.loads(dependent.dependency_ids_json or "[]")
                if dependent.id != record.id and parent_ids.intersection(dependency_ids):
                    dependent.dependency_ids_json = json.dumps([
                        record.id if dependency in parent_ids else dependency
                        for dependency in dependency_ids
                    ])
        record._completeness_created = True
        return record

    async def _rewire_repaired_dependencies(self, session, project_id):
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id))).scalars().all()
        candidates = {}
        for task in tasks:
            for ref in json.loads(task.context_refs_json or "[]"):
                if ref.get("source_type") == "completeness_reconciliation" and ref.get("parent_task_id"):
                    candidates.setdefault(ref["parent_task_id"], []).append(task)
        replacements = {}
        by_id = {task.id: task for task in tasks}
        repair_nodes = set(candidates) | {task.id for values in candidates.values() for task in values}
        for node in repair_nodes:
            descendants = []
            pending = list(candidates.get(node, []))
            seen = set()
            while pending:
                task = pending.pop()
                if task.id in seen:
                    continue
                seen.add(task.id)
                descendants.append(task)
                pending.extend(candidates.get(task.id, []))
            completed = [task for task in descendants if task.state == "completed"]
            if descendants:
                replacements[node] = max(completed or descendants, key=lambda task: (task.created_at, task.id)).id
        for task in tasks:
            dependencies = json.loads(task.dependency_ids_json or "[]")
            updated = [self._latest_repair(dependency, replacements) for dependency in dependencies]
            if updated != dependencies:
                task.dependency_ids_json = json.dumps(updated)

    def _latest_repair(self, task_id, replacements):
        seen = set()
        while task_id in replacements and task_id not in seen:
            seen.add(task_id)
            task_id = replacements[task_id]
        return task_id

    def _broken_python(self, root: Path) -> list[tuple[str, str]]:
        broken = []
        for path in root.rglob("*.py"):
            relative = path.relative_to(root)
            if IGNORED_PARTS.intersection(relative.parts):
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=relative.as_posix())
            except (SyntaxError, UnicodeError, OSError) as exc:
                broken.append((relative.as_posix(), f"{type(exc).__name__}: {exc}"))
        return broken

    def _surface_paths(self, root: Path) -> list[str]:
        expected = self._expected_surface_paths("business_system")
        return [path for path in expected if (root / path).is_file()]

    def _expected_surface_paths(self, project_type: str) -> list[str]:
        return ["frontend/src/App.tsx", "frontend/src/App.jsx", "frontend/src/main.tsx", "frontend/src/main.jsx", "frontend/index.html", "src/App.tsx", "src/App.jsx", "index.html"]

    def _surface_is_usable(self, root: Path, paths: list[str]) -> bool:
        text = "\n".join((root / path).read_text(encoding="utf-8", errors="ignore") for path in paths)
        lower = text.lower()
        return len(text) >= 1000 and sum(term in lower for term in ("login", "dashboard", "nav", "form", "fetch(", "api/")) >= 2

    def _has_live_task(self, tasks: list[OrchestrationTaskRecord], requirement_id: str, criteria: list[dict], root: Path | None = None) -> bool:
        """Report whether live work already carries this requirement's whole contract.

        Naming a requirement is not the same as proving it: a legacy task can list
        several requirements while its acceptance checks a single surface. Counting
        the reference as coverage left those requirements with no verifiable contract
        queued anywhere, so the loop could never converge on them. Evaluators are
        compared rather than criterion ids because a repair re-prefixes the ids it
        carries forward while preserving each evaluator verbatim.

        Criteria the workspace already satisfies are excluded when `root` is given.
        A repair drops those from the contract it carries forward, so demanding the
        full set read a repair as partial coverage and queued a second task for the
        same requirement: reconciliation produced both task-b727f1f403d0 and
        task-bb3439579748 for one shell requirement, each editing App.tsx. Coverage
        is about the part of the contract that does not hold yet.
        """
        required = [item["evaluator"] for item in criteria if item.get("evaluator")]
        if root is not None and required:
            evaluated = [item for item in criteria if item.get("evaluator")]
            statuses = WorkspaceAcceptanceService().evaluate(root, evaluated, [])
            required = [
                item["evaluator"]
                for item, result in zip(evaluated, statuses)
                if result["status"] != "passed"
            ]
        if not required:
            return False
        for task in tasks:
            if task.state not in LIVE_TASK_STATES or requirement_id not in self._requirement_ids(task):
                continue
            present = [item["evaluator"] for item in json.loads(task.acceptance_json or "[]") if item.get("evaluator")]
            if all(evaluator in present for evaluator in required):
                return True
        return False

    def _repair_key(self, task: OrchestrationTaskRecord) -> str | None:
        for ref in json.loads(task.context_refs_json or "[]"):
            if ref.get("source_type") == "completeness_reconciliation" and ref.get("dedupe_key"):
                return ref["dedupe_key"]
        return None

    def _is_repair(self, task: OrchestrationTaskRecord) -> bool:
        """Report whether this task is anchored to a partially executed origin task."""
        key = self._repair_key(task)
        return bool(key and key.startswith("partial:"))

    def _root_task(
        self,
        task: OrchestrationTaskRecord,
        index: dict[str, OrchestrationTaskRecord],
    ) -> OrchestrationTaskRecord:
        """Walk a repair chain back to the task that originally failed."""
        current = task
        seen: set[str] = set()
        while current.id not in seen:
            seen.add(current.id)
            parent = None
            for ref in json.loads(current.context_refs_json or "[]"):
                candidate = ref.get("origin_task_id") or ref.get("parent_task_id")
                if ref.get("source_type") == "completeness_reconciliation" and candidate:
                    parent = index.get(candidate)
                    break
            if parent is None or parent.id in seen:
                return current
            current = parent
        return current

    def _repair_capacity(self, tasks: list[OrchestrationTaskRecord], key: str, redundant: set[str] = frozenset()) -> bool:
        """Allow a repair for this anchor while a live one exists or the cap allows another."""
        generations = [task for task in tasks if self._repair_key(task) == key]
        if any(task.state in LIVE_TASK_STATES for task in generations):
            return True
        if any(task.state == "completed" for task in generations):
            # A repair already satisfied this anchor's acceptance; the origin task
            # staying `failed` is history, not outstanding work.
            return False
        if any(task.state == "cancelled" and task.id not in redundant for task in generations):
            # Cancelling a repair is a decision that this contract must not be
            # retried: the criteria it carries forward are unprovable, or they
            # contradict the project's actual structure. Recreating it reinstated
            # the same contract on the next pass and made retirement pointless.
            #
            # Retirement for redundancy is not that decision. It only records that
            # another live task covered the same outstanding work, so the anchor
            # stays open - otherwise a duplicate that is later cancelled itself
            # would leave the preserved partial work with nothing queued for it.
            return False
        return len(generations) < MAX_REPAIR_GENERATIONS

    def _reachability_scope(self, root: Path, criteria: list[dict]) -> list[str]:
        """Wiring points a repair needs to satisfy a reachability-bearing surface.

        `deliverable_surface` requires the surface be reachable from an application
        entry point (see defect: a screen no user can reach). Reachability is
        established only by importing the surface from a module already on the
        reachable graph, so a repair that carries such a criterion must be allowed to
        edit that graph. Returns the workspace-relative modules of the existing shell
        for every reachable-required surface among these criteria; empty when none
        apply, when reachability is disabled, or when the workspace has no entry point.
        """
        extra: list[str] = []
        acceptance = WorkspaceAcceptanceService()
        for criterion in criteria:
            evaluator = criterion.get("evaluator") or {}
            if evaluator.get("type") != "deliverable_surface":
                continue
            if not evaluator.get("require_reachable", True):
                continue
            paths: list[str] = []
            if evaluator.get("path"):
                paths.append(evaluator["path"])
            paths.extend(evaluator.get("paths", []))
            files = [root / value for value in paths]
            extra.extend(acceptance.reachable_modules(root, files))
        return list(dict.fromkeys(extra))

    def _scope_paths(self, task: OrchestrationTaskRecord) -> list[str]:
        paths: list[str] = []
        for criterion in json.loads(task.acceptance_json or "[]"):
            evaluator = criterion.get("evaluator") or {}
            if evaluator.get("path"):
                paths.append(evaluator["path"])
            paths.extend(evaluator.get("paths", []))
        for ref in json.loads(task.context_refs_json or "[]"):
            if ref.get("source_type") == "file" and ref.get("path"):
                paths.append(ref["path"])
            paths.extend(ref.get("paths", []))
        return list(dict.fromkeys(paths))

    def _criterion_paths(self, task: OrchestrationTaskRecord) -> set[str]:
        """Paths this task's acceptance criteria require the workspace to hold.

        Scope paths are excluded: `changed_files_subset` states where a task is
        permitted to write, not what it must deliver, so treating its paths as
        measured would freeze the entire blast radius of every interrupted attempt.
        Absence paths are excluded for the opposite reason: preserving a path another
        criterion requires gone would demand that the file both exist and not exist.
        """
        paths: set[str] = set()

        def walk(evaluator: dict) -> None:
            kind = evaluator.get("type")
            if kind in {"changed_files_subset", "path_absent"}:
                return
            if kind == "all_of":
                for check in evaluator.get("checks", []) or []:
                    walk(check)
                return
            if evaluator.get("path"):
                paths.add(str(evaluator["path"]))
            for value in evaluator.get("paths", []) or []:
                paths.add(str(value))

        for criterion in json.loads(task.acceptance_json or "[]"):
            walk(criterion.get("evaluator") or {})
        return paths

    def _removal_scope(self, criteria: list[dict]) -> list[str]:
        """Paths a carried `path_absent` criterion requires removed.

        Deletion is a change, so these have to be inside the measured scope or the
        contract contradicts itself. They are collected through `all_of` because that
        is how a requirement states a debris list: one criterion, several absences.
        """
        paths: list[str] = []

        def walk(evaluator: dict) -> None:
            kind = evaluator.get("type")
            if kind == "all_of":
                for check in evaluator.get("checks", []) or []:
                    walk(check)
            elif kind == "path_absent" and evaluator.get("path"):
                paths.append(str(evaluator["path"]))

        for criterion in criteria:
            walk(criterion.get("evaluator") or {})
        return list(dict.fromkeys(paths))

    def _outstanding_criteria(self, task: OrchestrationTaskRecord, key: str) -> list[dict]:
        """Carry forward the origin criteria that were never satisfied.

        Scope criteria are excluded because the repair replaces them with a single
        merged scope covering both the interrupted changes and the origin scope.
        """
        result = []
        for index, criterion in enumerate(json.loads(task.acceptance_json or "[]")):
            evaluator = criterion.get("evaluator") or {}
            if not evaluator.get("type") or evaluator["type"] == "changed_files_subset":
                continue
            if criterion.get("last_status") == "passed":
                continue
            result.append({
                "criterion_id": f"{key}:origin:{criterion.get('criterion_id', index)}",
                "description": criterion.get("description") or "Original acceptance criterion is still unsatisfied.",
                "evaluator": evaluator,
            })
        return result

    def _typed_requirement_acceptance(self, requirement: ProjectRequirementRecord) -> list[dict]:
        result = []
        for index, item in enumerate(json.loads(requirement.acceptance_json or "[]")):
            if item.get("evaluator", {}).get("type"):
                result.append({"criterion_id": item.get("criterion_id", f"requirement:{requirement.id}:{index}"), "description": item.get("description") or item.get("statement") or "Requirement acceptance passes.", "evaluator": item["evaluator"]})
        return result

    def _requirement_ids(self, task: OrchestrationTaskRecord) -> list[str]:
        return json.loads(task.requirement_ids_json or "[]")

    def _first_requirement(self, task: OrchestrationTaskRecord) -> str | None:
        values = self._requirement_ids(task)
        return values[0] if values else None

    def _repair_description(self, task: OrchestrationTaskRecord, receipt: dict) -> str:
        """State why the repair is open and what outranks the workspace, and stop there.

        The write boundary is deliberately not stated here. Dispatch renders it from
        the scope criterion, after the per-path obligations it bounds and gated on a
        criterion that measures it, so enumerating it again in the description adds no
        constraint - it repeats one, ahead of the specification instead of after it.
        The rendered prompt for task-1036cd4d6fc2 was 3406 characters, of which the
        same 1022-character 29-path allowlist occupied 2044, byte-identical at offsets
        854 and 2384, against 434 characters of specification - 12.7% - sandwiched
        between the two copies. attempt-c45095f2938a then ran 18m32s over 61 steps and
        4.79M tokens, obeyed the twice-stated boundary exactly (three files changed,
        `outside_scope: []`) and left both clauses the specification named unsatisfied:
        App.tsx still did not contain `Routes`, and the surface matched none of `route`.
        Four earlier attempts on the same contract stopped the same way.

        The merged scope is unaffected: it is carried by the `:scope` criterion that
        measures it, which is what makes the origin's own still-unsatisfied artifact
        writable. Deriving that boundary from only the interrupted attempt's changed
        files had forbidden the executor from creating the very file the repair is
        judged on.

        The interrupted attempt's process outcome is provenance, not an objective.
        Leading with it - "Continue and repair the preserved non_zero_exit work" -
        made a fact about a dead subprocess the headline of the run, and
        attempt-de1e80d8d515 spent 26 of its 56 tool calls hunting that exit code
        across `npm test`, `npm run build`, `npm run typecheck` and a standalone
        verifier before concluding, correctly and uselessly, that the earlier crash
        was transient Windows memory pressure. It then stopped with both paths its
        own contract had annotated `(fails now: does not contain requireRole)`
        untouched. A repair is open because acceptance is unsatisfied, and that is
        what the description has to say first.

        The criteria also have to be stated as outranking the workspace, because a
        generated workspace argues back. The same attempt read
        `ROLE_AUTHORIZATION.md` and `IMPLEMENTATION_SUMMARY.md` - both written by an
        earlier attempt at this requirement - found them documenting unguarded
        customer and order writes as intended design, and reported "role gates on
        all six business routers" while two routers carried none. Prose an executor
        produced is not a specification, and where it contradicts a criterion it is
        part of what needs repairing.
        """
        outcome = receipt.get("outcome") or "incomplete"
        return (
            f"Satisfy the unmet acceptance criteria below for '{task.title}'. "
            f"A previous attempt ended '{outcome}' and its partial changes are preserved in the workspace, which is "
            "why unfinished work is present. That outcome is context, not the task: do not spend this run "
            "reproducing, explaining or re-running it. "
            "The criteria below are the specification. Notes, summaries and documentation already in the workspace "
            "are earlier generated output, so where any of them disagrees with a criterion the criterion is "
            "authoritative and the document is part of what needs correcting. "
            "Acceptance measures the criteria below and nothing else: partial changes at paths no criterion names "
            "may be completed, moved into the measured paths, or removed. "
            "Inspect existing partial changes and complete the original requirement."
        )

    def _append_created(self, finding, task, findings: list[str], tasks: list[str]) -> None:
        # A dedupe hit returns a record created earlier in the same pass, and that
        # record still carries its creation flag, so the identity guard is what
        # keeps the reported set of new work from double-counting one task.
        if getattr(finding, "_completeness_created", False) and finding.id not in findings:
            findings.append(finding.id)
        if getattr(task, "_completeness_created", False) and task.id not in tasks:
            tasks.append(task.id)


completeness_reconciliation_service = CompletenessReconciliationService()
