import json
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import delete, select

from core.ai_fleet.services.completeness_reconciliation import CompletenessReconciliationService
from core.ai_fleet.services.workspace_acceptance import WorkspaceAcceptanceService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import (
    OrchestrationCheckpointRecord,
    OrchestrationTaskRecord,
    ProjectNeedRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    RunAttemptRecord,
    TaskRun,
    WorkspaceRecord,
)


class CompletenessReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:8]
        self.project_id = f"reconcile-project-{suffix}"
        self.workspace_id = f"reconcile-workspace-{suffix}"
        self.checkpoint_id = f"reconcile-checkpoint-{suffix}"
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Reconcile", slug=f"reconcile-{suffix}", project_type="business_system", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Reconcile", path=str(self.root), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(OrchestrationCheckpointRecord(id=self.checkpoint_id, project_id=self.project_id, state="approved", cursor_json="{}", ready_queue_json="[]", active_task_ids_json="[]", lock_keys_json="[]", revision=1))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            run_ids = (await session.execute(select(TaskRun.id).where(TaskRun.project_id == self.project_id))).scalars().all()
            if run_ids:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(run_ids)))
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
            if run_ids:
                await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
            await session.execute(delete(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == self.project_id))
            await session.execute(delete(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.id == self.checkpoint_id))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()
        self.temp.cleanup()

    async def _requirement(self, title="Customer workflow", description="Provide customer management", acceptance=None):
        # Typed, currently unsatisfied acceptance by default: reconciliation only
        # queues work it can mechanically prove, so a prose-only requirement is now
        # reported as a missing contract instead of becoming executable work.
        if acceptance is None:
            acceptance = [{"criterion_id": "workflow", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}}]
        record = ProjectRequirementRecord(
            id=f"requirement-{uuid.uuid4().hex[:8]}", project_id=self.project_id, title=title, description=description,
            requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved",
            acceptance_json=json.dumps(acceptance), evidence_json="[]",
        )
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
        return record.id

    async def _reconcile(self):
        async with AsyncSessionLocal() as session:
            return await CompletenessReconciliationService().reconcile(session, self.project_id, self.workspace_id, self.checkpoint_id)

    async def _seed_failed_task(self, title, changed_paths, acceptance, requirement_ids=(), context_refs=(), state="failed"):
        suffix = uuid.uuid4().hex[:8]
        task_id, run_id, attempt_id = f"task-{suffix}", f"run-{suffix}", f"attempt-{suffix}"
        receipt = {"outcome": "timed_out", "workspace_diff": [{"path": path, "before": None, "after": "hash", "change": "added"} for path in changed_paths]}
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt=title, project_id=self.project_id, workspace_id=self.workspace_id, status="timed_out"))
            session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=1, executor_type="agent", status="timed_out", outcome="timed_out", receipt_json=json.dumps(receipt)))
            session.add(OrchestrationTaskRecord(
                id=task_id, project_id=self.project_id, task_type="implementation", title=title,
                requirement_ids_json=json.dumps(list(requirement_ids)), acceptance_json=json.dumps(acceptance),
                context_refs_json=json.dumps(list(context_refs)), state=state, current_run_id=run_id,
            ))
            await session.commit()
        return task_id

    async def test_empty_queue_with_unmet_requirement_restores_executable_work(self):
        requirement_id = await self._requirement()
        result = await self._reconcile()
        self.assertEqual(result["status"], "executable")
        self.assertTrue(result["ready_queue"])
        self.assertFalse(result["assessment_ready"])
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, result["ready_queue"][0])
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
        self.assertIn(requirement_id, json.loads(task.requirement_ids_json))
        self.assertTrue(all(item.get("evaluator", {}).get("type") for item in json.loads(task.acceptance_json)))
        self.assertEqual(checkpoint.state, "approved")

    async def test_partial_timed_out_attempt_creates_bounded_repair_without_erasing_parent(self):
        requirement_id = await self._requirement()
        (self.root / "service.py").write_text("value = 1\n", encoding="utf-8")
        task_id, run_id, attempt_id = [f"{kind}-{uuid.uuid4().hex[:8]}" for kind in ("task", "run", "attempt")]
        receipt = {"outcome": "timed_out", "workspace_diff": [{"path": "service.py", "before": None, "after": "hash", "change": "added"}]}
        parent_acceptance = json.dumps([{"criterion_id": "old", "description": "Service exposes the workflow.", "evaluator": {"type": "path_exists_contains", "path": "service.py", "contains": ["def handle"]}}])
        dependent_acceptance = json.dumps([{"criterion_id": "dependent", "description": "Dependent module exists.", "evaluator": {"type": "paths_exist", "paths": ["dependent.py"]}}])
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="partial", project_id=self.project_id, workspace_id=self.workspace_id, status="timed_out"))
            session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=1, executor_type="agent", status="timed_out", outcome="timed_out", receipt_json=json.dumps(receipt)))
            session.add(OrchestrationTaskRecord(id=task_id, project_id=self.project_id, task_type="implementation", title="Partial feature", requirement_ids_json=json.dumps([requirement_id]), acceptance_json=parent_acceptance, state="failed", current_run_id=run_id))
            dependent_id = f"dependent-{uuid.uuid4().hex[:8]}"
            session.add(OrchestrationTaskRecord(id=dependent_id, project_id=self.project_id, task_type="implementation", title="Dependent feature", requirement_ids_json=json.dumps([requirement_id]), dependency_ids_json=json.dumps([task_id]), acceptance_json=dependent_acceptance, state="planned"))
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            parent = await session.get(OrchestrationTaskRecord, task_id)
            attempt = await session.get(RunAttemptRecord, attempt_id)
            dependent = await session.get(OrchestrationTaskRecord, dependent_id)
            repairs = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id, OrchestrationTaskRecord.id != task_id))).scalars().all()
        repair = next(item for item in repairs if "Repair incomplete work" in item.title)
        criteria = json.loads(repair.acceptance_json)
        self.assertEqual(parent.state, "failed")
        self.assertEqual(attempt.status, "timed_out")
        self.assertEqual(criteria[1]["evaluator"]["paths"], ["service.py"])
        self.assertEqual(json.loads(dependent.dependency_ids_json), [repair.id])
        self.assertIn(repair.id, result["ready_queue"])

    async def test_broken_python_artifact_creates_deduplicated_repair_finding(self):
        broken = self.root / "tests" / "test_generated.py"
        broken.parent.mkdir()
        broken.write_text("def unfinished(\n", encoding="utf-8")
        first = await self._reconcile()
        second = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id, ProjectNeedRecord.need_type == "broken_artifact"))).scalars().all()
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        syntax_tasks = [task for task in tasks if any(item.get("evaluator", {}).get("type") == "python_syntax_valid" for item in json.loads(task.acceptance_json))]
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(syntax_tasks), 1)
        self.assertTrue(first["ready_queue"])
        self.assertEqual(second["tasks_created"], [])

    async def test_missing_required_surface_creates_completion_task_and_rejects_placeholder(self):
        await self._requirement("Responsive application shell", "Provide browser login, dashboard, navigation, and responsive UI")
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<html><body>Placeholder</body></html>", encoding="utf-8")
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id, ProjectNeedRecord.need_type == "missing_deliverable_surface"))).scalars().all()
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        surface = next(task for task in tasks if task.title == "Complete required application surface")
        self.assertEqual(len(findings), 1)
        self.assertEqual(json.loads(surface.acceptance_json)[0]["evaluator"]["type"], "deliverable_surface")
        self.assertIn(surface.id, result["ready_queue"])

    async def test_checkpoint_returns_to_approved_executable_state(self):
        await self._requirement()
        async with AsyncSessionLocal() as session:
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
            checkpoint.state = "running"
            checkpoint.ready_queue_json = "[]"
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
        self.assertEqual(checkpoint.state, "approved")
        self.assertEqual(json.loads(checkpoint.ready_queue_json), result["ready_queue"])
        self.assertTrue(result["ready_queue"])

    async def test_failed_historical_requirement_task_does_not_block_new_recovery_task(self):
        requirement_id = await self._requirement()
        historical_id = f"historical-{uuid.uuid4().hex[:8]}"
        context = [{"source_type": "completeness_reconciliation", "dedupe_key": f"requirement:{requirement_id}", "finding_id": requirement_id}]
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(
                id=historical_id, project_id=self.project_id, task_type="implementation", title="Historical failed task",
                requirement_ids_json=json.dumps([requirement_id]), acceptance_json='[{"criterion_id":"old","description":"Old"}]',
                context_refs_json=json.dumps(context), state="failed",
            ))
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            created = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        recovery = [task for task in created if task.id != historical_id and task.state == "planned"]
        self.assertTrue(recovery)
        refs = json.loads(recovery[0].context_refs_json)
        self.assertTrue(any(ref.get("source_type") == "quality_repair_parent" and ref.get("parent_task_id") == historical_id for ref in refs))
        self.assertIn(recovery[0].id, result["ready_queue"])

    async def test_queued_task_satisfied_untouched_is_retired_and_unblocks_dependents(self):
        (self.root / "existing.ts").write_text("export const value = 1;\n", encoding="utf-8")
        vacuous_id, dependent_id = f"task-{uuid.uuid4().hex[:8]}", f"task-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(
                id=vacuous_id, project_id=self.project_id, task_type="implementation", title="Repair incomplete work: legacy",
                requirement_ids_json="[]", acceptance_json=json.dumps([
                    {"criterion_id": "files", "description": "Files remain present.", "evaluator": {"type": "paths_exist", "paths": ["existing.ts"]}},
                    {"criterion_id": "scope", "description": "Bounded.", "evaluator": {"type": "changed_files_subset", "paths": ["existing.ts"]}},
                ]), state="planned",
            ))
            session.add(OrchestrationTaskRecord(
                id=dependent_id, project_id=self.project_id, task_type="implementation", title="Real follow-up work",
                requirement_ids_json="[]", dependency_ids_json=json.dumps([vacuous_id]),
                acceptance_json=json.dumps([{"criterion_id": "real", "description": "New module exists.", "evaluator": {"type": "paths_exist", "paths": ["missing.ts"]}}]),
                state="planned",
            ))
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            vacuous = await session.get(OrchestrationTaskRecord, vacuous_id)
            dependent = await session.get(OrchestrationTaskRecord, dependent_id)
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id, ProjectNeedRecord.need_type == "unprovable_acceptance"))).scalars().all()
        self.assertEqual(vacuous.state, "cancelled")
        self.assertEqual(json.loads(dependent.dependency_ids_json), [])
        self.assertEqual(dependent.state, "planned")
        self.assertEqual(result["ready_queue"], [dependent_id])
        self.assertEqual(len(findings), 1)
        self.assertIn(findings[0].id, result["findings_created"])

    async def test_dispatch_guard_retires_vacuous_queue_without_a_reconciliation_pass(self):
        # Recovery can return a blocked task straight to the queue, so dispatch calls
        # the same provability guard directly. Without it a contract that already
        # passes untouched would be executed and recorded as completed work.
        (self.root / "existing.ts").write_text("export const value = 1;\n", encoding="utf-8")
        vacuous_id = f"task-{uuid.uuid4().hex[:8]}"
        real_id = f"task-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(
                id=vacuous_id, project_id=self.project_id, task_type="implementation", title="Recovered legacy repair",
                requirement_ids_json="[]", acceptance_json=json.dumps([
                    {"criterion_id": "files", "description": "Files remain present.", "evaluator": {"type": "paths_exist", "paths": ["existing.ts"]}},
                ]), state="planned",
            ))
            session.add(OrchestrationTaskRecord(
                id=real_id, project_id=self.project_id, task_type="implementation", title="Genuine work",
                requirement_ids_json="[]", acceptance_json=json.dumps([
                    {"criterion_id": "real", "description": "New module exists.", "evaluator": {"type": "paths_exist", "paths": ["missing.ts"]}},
                ]), state="planned",
            ))
            await session.commit()
        async with AsyncSessionLocal() as session:
            retired = await CompletenessReconciliationService().retire_unprovable_queue(session, self.project_id, self.workspace_id)
            await session.commit()
        async with AsyncSessionLocal() as session:
            vacuous = await session.get(OrchestrationTaskRecord, vacuous_id)
            real = await session.get(OrchestrationTaskRecord, real_id)
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id, ProjectNeedRecord.need_type == "unprovable_acceptance"))).scalars().all()
        self.assertEqual(vacuous.state, "cancelled")
        self.assertEqual(real.state, "planned")
        self.assertEqual(len(retired), 1)
        self.assertEqual([finding.id for finding in findings], retired)

    async def test_a_finding_about_a_settled_requirement_stops_blocking_delivery(self):
        """Defect #67: no blocking finding had any path to resolution but two.

        `_resolve_findings` was the only writer of `ProjectNeedRecord.state = "resolved"`
        anywhere in the engine, and the defect #65 fix reaches it with exactly two dedupe
        keys, both naming a requirement. `partial_execution`,
        `unprovable_acceptance`, `redundant_live_task` and
        `missing_deliverable_surface` could never be retired at all, and
        `CompletionAssessmentService.assess` blocks on every finding whose impact is
        blocking and whose state is `open` or `in_progress`. Delivery readiness was
        therefore unreachable however much work was proven - the same structural dead end
        as defect #65, by a different route and independent of it.

        Production evidence on project-23a514f0c426, 2026-08-22 02:17, measured
        immediately after the #65 fix credited five requirements on workspace acceptance:
        26 of 61 open blocking findings named one of those five now-`completed`
        requirements - 12 `partial_execution`, 10 `unprovable_acceptance` and 4
        `redundant_live_task` - each asserting outstanding or duplicated work on a
        requirement TEMM had just proven satisfied.

        The repair task is what keeps this honest, and it is asserted below: the finding
        stops blocking while the task it filed goes on blocking under `tasks` until its
        own criteria pass. Resolving a finding retires a claim, never a piece of work.
        """
        requirement_id = await self._requirement()
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "partial.ts").write_text("export const partial = 1;\n", encoding="utf-8")
        origin_id = await self._seed_failed_task(
            "Customer workflow",
            ["src/partial.ts"],
            [{"criterion_id": "origin", "description": "Handler exists.", "evaluator": {"type": "path_exists_contains", "path": "src/partial.ts", "contains": ["handleCustomer"]}}],
            requirement_ids=[requirement_id],
        )
        first = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        partial = next(item for item in findings if item.need_type == "partial_execution")
        self.assertEqual(partial.state, "open")
        self.assertEqual(partial.requirement_id, requirement_id)
        self.assertEqual(partial.source_id, origin_id)
        self.assertEqual(first["findings_resolved"], [])
        repair_id = next(item for item in first["tasks_created"] if item != origin_id)

        # The requirement is now satisfied on its own contract, by whatever route.
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        second = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            partial = await session.get(ProjectNeedRecord, partial.id)
            repair = await session.get(OrchestrationTaskRecord, repair_id)
        self.assertEqual(requirement.status, "completed")
        # The claim is retired, on the settlement that disproves it.
        self.assertEqual(partial.state, "resolved")
        self.assertIn(partial.id, second["findings_resolved"])
        self.assertIsNotNone(partial.resolved_at)
        resolution = json.loads(partial.resolution_json)
        self.assertEqual(resolution["reason"], "requirement_settled")
        self.assertEqual(resolution["requirement_id"], requirement_id)
        self.assertEqual(resolution["requirement_status"], "completed")
        self.assertEqual(resolution["source_type"], "workspace_acceptance")
        self.assertEqual(resolution["criteria"], [{"criterion_id": "workflow", "status": "passed"}])
        # And the work is not retired with it: the repair task's own criterion is still
        # unmet, so it goes on blocking delivery under `tasks` rather than under `needs`.
        self.assertEqual(repair.state, "planned")
        self.assertFalse(second["assessment_ready"])
        self.assertNotIn(partial.id, [item["id"] for item in second["blockers"]["needs"]])
        self.assertIn(repair_id, [item["task_id"] for item in second["blockers"]["tasks"]])

    async def test_a_finding_whose_requirement_is_still_open_is_never_retired(self):
        """The gate the fix must not open: this is not a sweep of the blocker count.

        Settlement is the only thing that retires a claim here, and settlement means
        `completed` - reachable only from a measured contract or a human transition - or
        `waived`, reachable only from a human one. An open requirement settles nothing,
        so every finding about it stands however inconvenient the count.
        """
        requirement_id = await self._requirement(acceptance=[
            {"criterion_id": "workflow", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
            {"criterion_id": "orders", "description": "Order module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/orders.ts"]}},
        ])
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        # One clause satisfied, one not, so the requirement stays approved.
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        (self.root / "src" / "partial.ts").write_text("export const partial = 1;\n", encoding="utf-8")
        await self._seed_failed_task(
            "Customer workflow",
            ["src/partial.ts"],
            [{"criterion_id": "origin", "description": "Handler exists.", "evaluator": {"type": "path_exists_contains", "path": "src/partial.ts", "contains": ["handleCustomer"]}}],
            requirement_ids=[requirement_id],
        )
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        self.assertEqual(requirement.status, "approved")
        self.assertEqual(result["requirements_credited"], [])
        self.assertEqual(result["findings_resolved"], [])
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(finding.state, "open", finding.need_type)
            self.assertIsNone(finding.resolution_json, finding.need_type)

    async def test_a_finding_waits_for_every_requirement_its_task_carries(self):
        """`requirement_id` records only the first, and a finding is about all of them.

        `_finding` is given `_first_requirement(origin)`, so a task spanning several
        requirements files a finding that names one. Settling that one does not settle
        what the finding is about, and retiring it then would drop a true claim about the
        requirements it never recorded.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        (self.root / "src" / "partial.ts").write_text("export const partial = 1;\n", encoding="utf-8")
        first_id = await self._requirement(acceptance=[
            {"criterion_id": "workflow", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
        ])
        second_id = await self._requirement(title="Order workflow", description="Provide order management", acceptance=[
            {"criterion_id": "orders", "description": "Order module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/orders.ts"]}},
        ])
        await self._seed_failed_task(
            "Customer and order workflow",
            ["src/partial.ts"],
            [{"criterion_id": "origin", "description": "Handler exists.", "evaluator": {"type": "path_exists_contains", "path": "src/partial.ts", "contains": ["handleCustomer"]}}],
            requirement_ids=[first_id, second_id],
        )
        # The first requirement is satisfied and credited; the second is not.
        held = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        partial = next(item for item in findings if item.need_type == "partial_execution")
        self.assertEqual(held["requirements_credited"], [first_id])
        self.assertEqual(partial.requirement_id, first_id, "The finding records only the first requirement.")
        self.assertEqual(partial.state, "open", "Its task still carries an unsettled requirement.")
        self.assertNotIn(partial.id, held["findings_resolved"])

        # Now the second requirement is satisfied too, so nothing the finding covers is
        # outstanding and the claim is retired.
        (self.root / "src" / "orders.ts").write_text("export const listOrders = () => [];\n", encoding="utf-8")
        released = await self._reconcile()
        async with AsyncSessionLocal() as session:
            partial = await session.get(ProjectNeedRecord, partial.id)
        self.assertEqual(released["requirements_credited"], [second_id])
        self.assertEqual(partial.state, "resolved")
        self.assertIn(partial.id, released["findings_resolved"])

    async def test_the_surface_finding_is_retired_by_the_measurement_that_files_it(self):
        """The findings that name no requirement, so settlement can never reach them.

        `missing_deliverable_surface` is filed with `requirement_id=None` against the
        workspace itself, which left it with no route to resolution whatever - it would
        have blocked delivery for the life of the project even once the surface it asks
        for existed. It is retired by the pass's own silence: the condition that files it
        is re-computed in full on every pass, so a pass that does not re-file it has
        measured that its premise no longer holds.
        """
        await self._requirement(title="Responsive shell", description="Provide a dashboard and responsive navigation")
        first = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        surface = next(item for item in findings if item.need_type == "missing_deliverable_surface")
        self.assertEqual(surface.state, "open")
        self.assertIsNone(surface.requirement_id, "Nothing about a requirement can reach this finding.")
        self.assertEqual(first["findings_resolved"], [])

        # A real surface: over 1000 characters and more than one required affordance.
        (self.root / "frontend" / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend" / "src" / "App.tsx").write_text(
            "import { useEffect, useState } from 'react';\n"
            "export const App = () => {\n"
            "  const [rows, setRows] = useState([]);\n"
            "  useEffect(() => { fetch('/api/customers').then(r => r.json()).then(setRows); }, []);\n"
            "  return (\n"
            "    <div className='shell'>\n"
            "      <nav aria-label='Primary navigation'><a href='/dashboard'>Dashboard</a></nav>\n"
            "      <form onSubmit={event => event.preventDefault()}><label>Login<input name='login' /></label></form>\n"
            "      <main>{rows.map(row => <article key={row.id}>{row.name}</article>)}</main>\n"
            "    </div>\n"
            "  );\n"
            "};\n" + "// dashboard navigation shell padding to a realistic module size\n" * 14,
            encoding="utf-8",
        )
        second = await self._reconcile()
        async with AsyncSessionLocal() as session:
            surface = await session.get(ProjectNeedRecord, surface.id)
        self.assertEqual(surface.state, "resolved")
        self.assertIn(surface.id, second["findings_resolved"])
        resolution = json.loads(surface.resolution_json)
        self.assertEqual(resolution["reason"], "premise_no_longer_observed")
        self.assertEqual(resolution["need_type"], "missing_deliverable_surface")
        self.assertEqual(resolution["source_type"], "completeness_reconciliation")
        self.assertNotIn(surface.id, [item["id"] for item in second["blockers"]["needs"]])

        # And it is not a latch. A surface that regresses is a finding again, because
        # `_finding` reopens a resolved record the moment its condition recurs - so the
        # state tracks the workspace rather than the first time it was ever measured.
        (self.root / "frontend" / "src" / "App.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
        third = await self._reconcile()
        async with AsyncSessionLocal() as session:
            surface = await session.get(ProjectNeedRecord, surface.id)
        self.assertEqual(surface.state, "open")
        self.assertIsNone(surface.resolution_json)
        self.assertNotIn(surface.id, third["findings_resolved"])
        self.assertIn(surface.id, [item["id"] for item in third["blockers"]["needs"]])

    async def test_a_repaired_artifact_stops_blocking_when_it_parses(self):
        """The second finding filed against no requirement, retired by the same rule.

        `broken_artifact` names a file rather than a requirement, so like the surface
        finding it had no route to resolution: a generated Python file that failed to
        parse blocked delivery for the life of the project, even after it was repaired.
        It is retired by the same equivalence, because `_broken_python` walks every Python
        file in the workspace on every pass - so a pass that files nothing for a path has
        measured that path as parsing.

        This is one rule rather than two because the two types share the property that
        licenses it: their filing condition is re-computed in full and unconditionally on
        every pass, which is what makes the pass's silence a measurement rather than an
        absence of one. A finding filed conditionally could not be resolved this way -
        its silence would mean the condition was never reached.
        """
        await self._requirement()
        (self.root / "backend").mkdir(parents=True, exist_ok=True)
        broken = self.root / "backend" / "seed.py"
        broken.write_text("def seed(:\n    return 1\n", encoding="utf-8")
        first = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        syntax = next(item for item in findings if item.need_type == "broken_artifact")
        self.assertEqual(syntax.state, "open")
        self.assertIsNone(syntax.requirement_id, "Nothing about a requirement can reach this finding.")
        self.assertEqual(syntax.source_id, "backend/seed.py")
        self.assertEqual(syntax.dedupe_key, "completeness:syntax:backend/seed.py")
        self.assertEqual(first["findings_resolved"], [])
        self.assertIn(syntax.id, [item["id"] for item in first["blockers"]["needs"]])

        broken.write_text("def seed():\n    return 1\n", encoding="utf-8")
        second = await self._reconcile()
        async with AsyncSessionLocal() as session:
            syntax = await session.get(ProjectNeedRecord, syntax.id)
        self.assertEqual(syntax.state, "resolved")
        self.assertIn(syntax.id, second["findings_resolved"])
        self.assertIsNotNone(syntax.resolved_at)
        resolution = json.loads(syntax.resolution_json)
        self.assertEqual(resolution["reason"], "premise_no_longer_observed")
        self.assertEqual(resolution["need_type"], "broken_artifact")
        self.assertNotIn(syntax.id, [item["id"] for item in second["blockers"]["needs"]])

    async def test_the_lapse_rule_retires_only_the_path_that_healed(self):
        """A per-path finding is resolved per path, not per type.

        The lapse rule keys on what the pass observed, so two broken files are two
        premises and repairing one says nothing about the other. Resolving by type would
        clear both from one repair, which is the failure mode a blocker sweep has and
        this rule must not.
        """
        await self._requirement()
        (self.root / "backend").mkdir(parents=True, exist_ok=True)
        first_file = self.root / "backend" / "seed.py"
        second_file = self.root / "backend" / "migrate.py"
        first_file.write_text("def seed(:\n    return 1\n", encoding="utf-8")
        second_file.write_text("def migrate(:\n    return 2\n", encoding="utf-8")
        await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        by_source = {item.source_id: item for item in findings if item.need_type == "broken_artifact"}
        self.assertEqual(sorted(by_source), ["backend/migrate.py", "backend/seed.py"])

        first_file.write_text("def seed():\n    return 1\n", encoding="utf-8")
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            healed = await session.get(ProjectNeedRecord, by_source["backend/seed.py"].id)
            still_broken = await session.get(ProjectNeedRecord, by_source["backend/migrate.py"].id)
        self.assertEqual(healed.state, "resolved")
        self.assertEqual(result["findings_resolved"], [healed.id])
        self.assertEqual(still_broken.state, "open", "The file that still does not parse still blocks.")
        self.assertIsNone(still_broken.resolution_json)
        self.assertIn(still_broken.id, [item["id"] for item in result["blockers"]["needs"]])

    async def test_a_measurably_satisfied_requirement_is_credited_rather_than_called_contract_less(self):
        """Defect #65: proving a requirement made TEMM record that it could not be proven.

        The requirement pass reported a missing acceptance contract whenever
        `_is_provable` was false, and that is false for two opposite contracts: one with
        no typed clause, and one whose every typed clause passes. The second is the
        requirement being finished. Nothing anywhere in the engine wrote
        `status = "completed"` either - `RequirementService.transition` is reachable only
        from `POST /projects/requirements/{id}/transition` - and
        `CompletionAssessmentService` blocks on every requirement that is not `completed`
        or `waived`, so delivery readiness was unreachable by construction.

        Production evidence on project-23a514f0c426, 2026-08-22 01:07: ten requirements,
        all ten `approved`, all ten holding two to four typed evaluators, and five of
        them simultaneously on record as having "no verifiable acceptance contract". The
        newest of the five was filed at 2026-08-22 00:18:13 against `Customer
        management`, whose three clauses had just started passing because the defect #63
        fix stopped acceptance reading substance in a re-export barrel. The fleet
        delivered the screen, then filed the delivery as an unprovable contract.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => fetch('/api/customers');\n", encoding="utf-8")
        requirement_id = await self._requirement(acceptance=[
            {"criterion_id": "customers:module", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
            {"criterion_id": "customers:wiring", "description": "Customer module calls the API.", "evaluator": {"type": "path_exists_contains", "path": "src/customers.ts", "contains": ["/api/customers"]}},
        ])
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            evidence = json.loads(requirement.evidence_json or "[]")
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        # The requirement is credited, and the measurement is what makes it legal.
        self.assertEqual(requirement.status, "completed")
        self.assertEqual(result["requirements_credited"], [requirement_id])
        self.assertEqual(len(evidence), 1, evidence)
        self.assertEqual(evidence[0]["source_type"], "workspace_acceptance")
        self.assertEqual(evidence[0]["workspace_id"], self.workspace_id)
        self.assertEqual(
            sorted(item["criterion_id"] for item in evidence[0]["criteria"]),
            ["customers:module", "customers:wiring"],
        )
        self.assertTrue(all(item["status"] == "passed" for item in evidence[0]["criteria"]), evidence)
        # Nothing was said about a missing contract, and no work was queued for a
        # requirement that is done.
        self.assertEqual([finding.need_type for finding in findings if finding.state != "resolved"], [])
        self.assertEqual([finding.need_type for finding in findings if finding.need_type == "missing_acceptance_contract"], [])
        self.assertEqual(tasks, [])
        self.assertEqual(result["tasks_created"], [])
        self.assertEqual(result["ready_queue"], [])
        # The payoff, and the reason this defect made completion unreachable rather
        # than merely mis-stated: with the only requirement credited on evidence,
        # delivery readiness is decided by measurement instead of being impossible.
        self.assertTrue(result["assessment_ready"], result["blockers"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["blockers"]["requirements"], [])

    async def test_crediting_resolves_the_findings_its_own_measurement_disproves(self):
        """A finding that has become false must stop blocking, on the evidence.

        `_finding` was the only writer of `ProjectNeedRecord.state` and it only ever
        wrote `open`, reopening a resolved record. So the two findings that name a
        requirement - it is unresolved, and it has no verifiable contract - outlived the
        measurement that disproved both. This closes exactly those two and records the
        measurement as the resolution, which is the evidence loop closing rather than a
        blocker being cleared: every other finding on the project is left untouched.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        requirement_id = await self._requirement(acceptance=[
            {"criterion_id": "customers:module", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
        ])
        # First pass, with the file absent: the requirement is unmet and gets a task.
        first = await self._reconcile()
        self.assertEqual(len(first["tasks_created"]), 1, first)
        # An unrelated blocking finding, to prove the resolution is targeted.
        unrelated_id = f"need-{uuid.uuid4().hex[:12]}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectNeedRecord(
                id=unrelated_id, project_id=self.project_id, need_type="partial_execution", title="Unrelated",
                description="An unrelated blocking concern.", source_type="completeness_reconciliation",
                source_id="task-unrelated", impact="blocking", blocked_nodes_json="[]", state="open",
                dedupe_key="completeness:partial:task-unrelated",
            ))
            await session.commit()
        # Now the work exists, so the same contract measures satisfied.
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        second = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            findings = {finding.dedupe_key: finding for finding in (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()}
        self.assertEqual(requirement.status, "completed")
        self.assertEqual(second["requirements_credited"], [requirement_id])
        unresolved_finding = findings[f"completeness:requirement:{requirement_id}"]
        self.assertEqual(unresolved_finding.state, "resolved")
        self.assertIsNotNone(unresolved_finding.resolved_at)
        self.assertEqual(json.loads(unresolved_finding.resolution_json)["criteria"], [{"criterion_id": "customers:module", "status": "passed"}])
        # Targeted: an unrelated blocking finding is nobody else's to close.
        self.assertEqual(findings["completeness:partial:task-unrelated"].state, "open")
        self.assertIsNone(findings["completeness:partial:task-unrelated"].resolution_json)

    async def test_a_satisfied_requirement_that_cannot_be_completed_is_never_called_contract_less(self):
        """Legality is the transition table's to decide, and truth is still truth.

        A `draft` requirement has not been approved and `TRANSITIONS` will not complete
        it, which is right - approval is a human act and a measurement is not a
        substitute for one. What must not happen is the other half of defect #65: the
        contract is typed and every clause of it passes, so reporting that the
        requirement has no verifiable acceptance contract would be false whatever its
        status. It stays reported as unresolved, because it is.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        requirement_id = await self._requirement(acceptance=[
            {"criterion_id": "customers:module", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
        ])
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            requirement.status = "draft"
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        self.assertEqual(requirement.status, "draft", "A measurement must not approve a requirement.")
        self.assertEqual(json.loads(requirement.evidence_json or "[]"), [])
        self.assertEqual(result["requirements_credited"], [])
        self.assertEqual([finding.need_type for finding in findings], ["unresolved_requirement"])
        self.assertEqual(findings[0].state, "open")
        # And no work is queued for a contract that is already satisfied, which would
        # be a completion recorded for work that never happened.
        self.assertEqual(tasks, [])

    async def test_a_partly_satisfied_requirement_is_still_queued_and_never_credited(self):
        """The gate the fix must not open: one failing clause is an unmet requirement."""
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "customers.ts").write_text("export const listCustomers = () => [];\n", encoding="utf-8")
        requirement_id = await self._requirement(acceptance=[
            {"criterion_id": "customers:module", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}},
            {"criterion_id": "customers:orders", "description": "Order module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/orders.ts"]}},
        ])
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            requirement = await session.get(ProjectRequirementRecord, requirement_id)
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id))).scalars().all()
        self.assertEqual(requirement.status, "approved")
        self.assertEqual(json.loads(requirement.evidence_json or "[]"), [])
        self.assertEqual(result["requirements_credited"], [])
        self.assertEqual(len(result["tasks_created"]), 1, result)
        self.assertEqual([finding.need_type for finding in findings], ["unresolved_requirement"])
        self.assertFalse(result["assessment_ready"])

    async def test_prose_only_requirement_reports_missing_contract_instead_of_queueing_work(self):
        requirement_id = await self._requirement(acceptance=[{"statement": "Workflow works"}])
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            findings = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == self.project_id, ProjectNeedRecord.need_type == "missing_acceptance_contract"))).scalars().all()
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        self.assertEqual(result["tasks_created"], [])
        self.assertEqual(tasks, [])
        self.assertEqual(result["ready_queue"], [])
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["assessment_ready"])
        self.assertEqual([finding.requirement_id for finding in findings], [requirement_id])

    async def test_repair_carries_unsatisfied_origin_criteria_and_merged_scope(self):
        acceptance = [
            {"criterion_id": "kept", "description": "Existing module preserved.", "evaluator": {"type": "paths_exist", "paths": ["kept.ts"]}, "last_status": "passed"},
            {"criterion_id": "feature", "description": "Login UI is present.", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/App.tsx", "needles": ["login"]}},
            {"criterion_id": "bounded", "description": "Origin scope.", "evaluator": {"type": "changed_files_subset", "paths": ["frontend/src/App.tsx"]}},
            {"criterion_id": "reviewed", "description": "Reviewer confirms quality."},
        ]
        origin_id = await self._seed_failed_task("Login surface", ["partial.ts"], acceptance)
        result = await self._reconcile()
        self.assertEqual(len(result["tasks_created"]), 1)
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = {item["criterion_id"]: item for item in json.loads(repair.acceptance_json)}
        self.assertEqual(criteria[f"{key}:origin:feature"]["evaluator"]["type"], "path_exists_contains")
        self.assertNotIn(f"{key}:origin:kept", criteria)
        self.assertNotIn(f"{key}:origin:bounded", criteria)
        self.assertNotIn(f"{key}:origin:reviewed", criteria)
        self.assertNotIn(f"{key}:files", criteria, "No criterion measures partial.ts, so the repair is not obliged to keep it.")
        # The measured boundary must admit the artifact the repair is judged on;
        # deriving it from only the interrupted attempt's files forbade that file.
        # This criterion is where the boundary lives - the prompt renders it from
        # here, and the description does not restate it (see the composition test).
        self.assertEqual(criteria[f"{key}:scope"]["evaluator"]["paths"], ["partial.ts", "kept.ts", "frontend/src/App.tsx"])

    async def test_the_write_boundary_is_stated_once_and_after_what_it_bounds(self):
        """Defect #59: two emitters for one boundary, with the specification buried between.

        Dispatch already renders the write boundary from the scope criterion, gated on
        a criterion that measures it, immediately after the per-path obligations it
        bounds. A description that enumerates the same allowlist does not add a second
        constraint - it repeats the one constraint, 1500 characters ahead of the
        specification, and pays for it in the specification's share of the prompt.

        Production evidence 2026-08-21, the rendered prompt for task-1036cd4d6fc2:
        3406 characters, of which the same 1022-character 29-path allowlist occupied
        2044 - byte-identical at offsets 854 and 2384 - against 434 characters of
        specification, 12.7%, sandwiched between the two copies.
        attempt-c45095f2938a then ran 18m32s over 61 steps and 4,790,677 tokens,
        obeyed the twice-stated boundary exactly (three files changed,
        `outside_scope: []`), and left both clauses the specification named
        unsatisfied: App.tsx still did not contain `Routes`, and the deliverable
        surface matched none of `route`. Four earlier attempts on the same contract
        stopped the same way.

        This asserts the composition, not either half of it: the description and the
        dispatcher are separate emitters and only the rendered prompt shows what the
        executor is actually asked.
        """
        from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService

        measured = [f"frontend/src/pages/Screen{index}.tsx" for index in range(9)]
        acceptance = [
            {"criterion_id": "wired", "description": "Router is wired.", "evaluator": {"type": "path_exists_contains", "path": measured[0], "contains": ["Routes"]}},
            {"criterion_id": "bounded", "description": "Origin scope.", "evaluator": {"type": "changed_files_subset", "paths": measured}},
        ]
        await self._seed_failed_task("Navigation surface", ["partial.tsx"], acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        prompt = ProjectDispatcherService(None)._prompt(repair, str(self.root))

        allowlist = ", ".join(["partial.tsx", *measured])
        self.assertIn(allowlist, prompt, "The boundary must still be stated - it is one constraint, not none.")
        self.assertEqual(prompt.count(allowlist), 1, "One constraint, stated once.")
        self.assertNotIn(allowlist, repair.description, "The description must not restate what dispatch renders.")
        # Stated after the obligations it bounds, so the specification is not read
        # through a path list on the way in.
        self.assertLess(prompt.index("Routes"), prompt.index(allowlist))
        # The path list must not outweigh everything else the prompt says. Two copies
        # of it were 60.0% of the production prompt.
        self.assertLess(len(allowlist), len(prompt) / 2, "The boundary is a constraint, not the brief.")

    async def test_repair_objective_is_acceptance_not_the_previous_process_outcome(self):
        """A dead subprocess's exit status is provenance, not the job.

        Production evidence 2026-08-21: the repair for `rbac:destructive-guards` was
        described as "Continue and repair the preserved non_zero_exit work", and
        attempt-de1e80d8d515 spent 26 of 56 tool calls chasing that exit code through
        `npm test`, `npm run build` and `npm run typecheck` before correctly
        attributing it to transient Windows memory pressure - then stopped without
        touching either path the same prompt annotated `(fails now: does not contain
        requireRole)`. The outcome may still appear as the reason partial work is
        present; it may not be what the description asks for.

        The description must also rank the criteria above the workspace's own prose.
        That attempt read `ROLE_AUTHORIZATION.md` and `IMPLEMENTATION_SUMMARY.md`,
        both generated by an earlier attempt at this requirement, found unguarded
        customer and order writes documented as intended design, and reported "role
        gates on all six business routers" while two routers carried none.
        """
        acceptance = [
            {"criterion_id": "guard", "description": "Route carries a role guard.", "evaluator": {"type": "path_exists_contains", "path": "routes.ts", "contains": ["requireRole"]}},
        ]
        origin_id = await self._seed_failed_task("Role authorization", ["routes.ts"], acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        opening = repair.description.split(". ")[0]
        self.assertIn("acceptance criteria", opening, opening)
        self.assertNotIn("timed_out", opening, "The previous outcome is not the objective.")
        self.assertIn("timed_out", repair.description, "It is still stated as why partial work exists.")
        self.assertIn("do not spend this run", repair.description)
        self.assertIn("the criterion is", repair.description)
        self.assertIn("documentation already in the workspace", repair.description)
        self.assertIn("complete the original requirement", repair.description)

    async def test_queued_repair_is_restated_when_reconciliation_runs_again(self):
        """Queued work must ask for what reconciliation currently computes.

        A dedupe hit returned the existing record untouched, so a repair kept the
        wording and the criteria it was born with. Defect #51 corrected how a repair
        states its objective and reached none of the three NEXA repairs already
        sitting in the queue. Restating a `planned`, never-dispatched task is safe:
        nothing has been measured against it yet.
        """
        acceptance = [
            {"criterion_id": "guard", "description": "Route carries a role guard.", "evaluator": {"type": "path_exists_contains", "path": "routes.ts", "contains": ["requireRole"]}},
        ]
        origin_id = await self._seed_failed_task("Role authorization", ["routes.ts"], acceptance)
        first = await self._reconcile()
        repair_id = first["tasks_created"][0]
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, repair_id)
            repair.description = "stale wording from an earlier reconciliation"
            repair.acceptance_json = json.dumps([{"criterion_id": "stale", "evaluator": {"type": "paths_exist", "paths": ["stale.ts"]}}])
            await session.commit()
        second = await self._reconcile()
        self.assertNotIn(repair_id, second["tasks_created"], "The anchor is covered; restating it must not clone it.")
        async with AsyncSessionLocal() as session:
            refreshed = await session.get(OrchestrationTaskRecord, repair_id)
        self.assertIn("acceptance criteria", refreshed.description)
        self.assertIn("complete the original requirement", refreshed.description)
        self.assertIn(f"partial:{origin_id}:scope", [item["criterion_id"] for item in json.loads(refreshed.acceptance_json)])
        self.assertEqual(
            [ref.get("dedupe_key") for ref in json.loads(refreshed.context_refs_json) if ref.get("dedupe_key")],
            [f"partial:{origin_id}"],
            "Identity survives a restatement.",
        )

    async def test_dispatched_repair_is_never_restated_underneath_its_run(self):
        """A contract being measured is not a contract to rewrite.

        Once a task holds a run, an executor is reading its words or an attempt is
        already being judged against its criteria, so restating either would move
        the goalposts under evidence that has already been produced.
        """
        acceptance = [
            {"criterion_id": "guard", "description": "Route carries a role guard.", "evaluator": {"type": "path_exists_contains", "path": "routes.ts", "contains": ["requireRole"]}},
        ]
        await self._seed_failed_task("Role authorization", ["routes.ts"], acceptance)
        first = await self._reconcile()
        repair_id = first["tasks_created"][0]
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, repair_id)
            repair.description = "the words this attempt is executing"
            repair.state = "running"
            repair.current_run_id = "run-underway"
            await session.commit()
        await self._reconcile()
        async with AsyncSessionLocal() as session:
            refreshed = await session.get(OrchestrationTaskRecord, repair_id)
        self.assertEqual(refreshed.description, "the words this attempt is executing")

    async def test_repair_scope_admits_the_removal_its_own_criterion_demands(self):
        """A contract may not forbid the deletion it measures.

        `changed_files_subset` fails on any changed path outside its list, and a
        deletion is a change. TEMM told attempt-0510cc86c1cf that `__inspect_db.cjs`,
        `debug-db.js`, `seed.js` and `seed-data.js` must not exist and, three lines
        later, not to modify anything outside 36 paths that named none of them. The
        run left all four in place - the only reading of that contract which its own
        scope criterion could pass - and `delivery:no-debris` failed again.

        Preservation is the mirror of the same rule: a path an absence criterion
        requires gone can never be a path the repair must keep, or the contract would
        demand that one file both exist and not exist.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "feature.ts").write_text("export const feature = 1;\n", encoding="utf-8")
        (self.root / "debris.js").write_text("console.log('scratch');\n", encoding="utf-8")
        acceptance = [
            {"criterion_id": "feature", "description": "Feature is implemented.", "evaluator": {"type": "path_exists_contains", "path": "src/feature.ts", "contains": ["handle"]}},
            {"criterion_id": "clean", "description": "No debris ships.", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debris.js"}, {"type": "path_absent", "path": "scratch.js"}]}},
        ]
        origin_id = await self._seed_failed_task("Distributable package", ["debris.js", "src/feature.ts"], acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = json.loads(repair.acceptance_json)
        by_id = {item["criterion_id"]: item for item in criteria}
        scope = by_id[f"{key}:scope"]["evaluator"]["paths"]
        self.assertIn("debris.js", scope, "Deleting a file is a change to it, so the boundary has to admit the path.")
        self.assertIn("scratch.js", scope, "Absences are collected through all_of: that is how a debris list is stated.")
        self.assertEqual(by_id[f"{key}:files"]["evaluator"]["paths"], ["src/feature.ts"])
        self.assertNotIn("debris.js", by_id[f"{key}:files"]["evaluator"]["paths"], "Preserving a path another criterion requires gone is a contradiction.")
        # The permission has to reach the executor, and it does through the prompt's
        # single boundary line, which dispatch renders from this criterion.
        from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService

        boundary = next(
            line for line in ProjectDispatcherService(None)._prompt(repair, str(self.root)).splitlines()
            if line.startswith("Do not modify anything outside:")
        )
        self.assertIn("debris.js", boundary)
        # The repair the contract now permits: implement the feature, delete the debris.
        (self.root / "src" / "feature.ts").write_text("export const handle = () => 1;\n", encoding="utf-8")
        (self.root / "debris.js").unlink()
        diff = [{"path": "debris.js", "change": "deleted"}, {"path": "src/feature.ts", "change": "modified"}]
        results = WorkspaceAcceptanceService().evaluate(self.root, criteria, diff)
        self.assertEqual([item["status"] for item in results], ["passed"] * len(criteria), results)

    async def test_repair_scope_admits_the_files_its_own_all_of_checks_measure(self):
        """A contract may not forbid editing the files it measures.

        A requirement spanning several files is stated as one `all_of` whose inner
        checks carry the paths. The scope collector reads an evaluator's own
        `path`/`paths` keys, and an `all_of` has neither, so those paths reached the
        boundary through nothing: the widenings beside it answer only
        `deliverable_surface` reachability and `path_absent` removals.
        `changed_files_subset` admits a repair only the paths its own list names, so
        the repair was refused for touching the exact files acceptance reads.

        Production evidence 2026-08-22. task-5e3303d8e2e2, minted for
        task-b4afa6822e1f's RBAC requirement, was scoped to `ACCEPTANCE_SUMMARY.md`,
        `backend/src/app.ts` and `backend/src/tests/rbac.test.ts` - what the
        interrupted attempt happened to write - while its carried `all_of` measures
        `requireRole` in `backend/src/routes/customers.ts`, `products.ts` and
        `orders.ts`. Three permitted paths, none of them measured; three measured
        paths, none of them permitted. The repair for one of three remaining
        requirements was unsatisfiable at birth.
        """
        routes = self.root / "backend" / "src" / "routes"
        routes.mkdir(parents=True, exist_ok=True)
        measured = ["backend/src/routes/customers.ts", "backend/src/routes/products.ts", "backend/src/routes/orders.ts"]
        for value in measured:
            (self.root / value).write_text("export const router = 1;", encoding="utf-8")
        written = ["ACCEPTANCE_SUMMARY.md", "backend/src/app.ts", "backend/src/tests/rbac.test.ts"]
        for value in written:
            target = self.root / value
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder", encoding="utf-8")
        acceptance = [
            {"criterion_id": "rbac", "description": "Every route enforces a role.", "evaluator": {"type": "all_of", "checks": [
                {"type": "path_exists_contains", "path": value, "contains": ["requireRole"]} for value in measured
            ]}},
        ]
        origin_id = await self._seed_failed_task("Role-based access control", written, acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = json.loads(repair.acceptance_json)
        by_id = {item["criterion_id"]: item for item in criteria}
        scope = by_id[f"{key}:scope"]["evaluator"]["paths"]
        for value in measured:
            self.assertIn(value, scope, "A path acceptance reads has to be a path the repair may write.")
        for value in written:
            self.assertIn(value, scope, "The interrupted attempt's own changes stay inside the boundary.")

        # The permission has to reach the executor, and it does through the single
        # boundary line dispatch renders from this criterion.
        from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService

        boundary = next(
            line for line in ProjectDispatcherService(None)._prompt(repair, str(self.root)).splitlines()
            if line.startswith("Do not modify anything outside:")
        )
        for value in measured:
            self.assertIn(value, boundary, boundary)

        # The repair the contract now permits: guard all three routes.
        for value in measured:
            (self.root / value).write_text("import { requireRole } from '../auth'; export const router = requireRole;", encoding="utf-8")
        diff = [{"path": value, "change": "modified"} for value in measured]
        results = WorkspaceAcceptanceService().evaluate(self.root, criteria, diff)
        self.assertEqual([item["status"] for item in results], ["passed"] * len(criteria), results)

    async def test_repair_may_move_interrupted_work_to_the_path_the_contract_names(self):
        """A near-miss filename must not become a mandatory deliverable.

        Production evidence: `attempt-a1f4dce3c08b` was refused by its provider after
        writing the whole 12,367-character customers screen to
        `frontend/src/pages/CustomerPage.tsx`, while the criteria it was judged on
        measured `frontend/src/pages/CustomersPage.tsx`. The repair contract froze
        every path the refused attempt had touched and told the executor that all of
        them must be present when it stopped, so the one correct repair - move the
        screen to the path acceptance names - was forbidden. `attempt-753bc981e2a1`
        obeyed both clauses the only way they allow: it kept the misnamed screen and
        re-exported it from the contracted path in 57 characters, which failed a
        1500-character surface criterion and left two files for one screen.
        """
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        misnamed = self.root / "src" / "CustomerPage.tsx"
        misnamed.write_text("const CustomersPage = () => fetch('/api/customers');\nexport default CustomersPage;\n", encoding="utf-8")
        acceptance = [
            {"criterion_id": "screen", "description": "Customers screen is present.", "evaluator": {"type": "path_exists_contains", "path": "src/CustomersPage.tsx", "contains": ["/api/customers"]}},
        ]
        origin_id = await self._seed_failed_task("Customer management", ["src/CustomerPage.tsx"], acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = json.loads(repair.acceptance_json)
        by_id = {item["criterion_id"]: item for item in criteria}
        self.assertNotIn(f"{key}:files", by_id, "The refused attempt's near-miss filename is not a deliverable.")
        self.assertIn("src/CustomerPage.tsx", by_id[f"{key}:scope"]["evaluator"]["paths"], "Relocation has to stay inside the measured boundary.")
        self.assertIn(f"{key}:origin:screen", by_id)
        # The repair the contract now permits: the screen moves to the path acceptance
        # names, and the misnamed file goes away instead of being re-exported.
        (self.root / "src" / "CustomersPage.tsx").write_text(misnamed.read_text(encoding="utf-8"), encoding="utf-8")
        misnamed.unlink()
        results = WorkspaceAcceptanceService().evaluate(self.root, criteria, [{"path": "src/CustomerPage.tsx", "change": "deleted"}, {"path": "src/CustomersPage.tsx", "change": "added"}])
        self.assertEqual([item["status"] for item in results], ["passed"] * len(criteria), results)

    async def test_repair_that_deletes_measured_origin_work_still_fails_preservation(self):
        """Narrowing preservation may not license a repair to undo proven work.

        A path an origin criterion measures is work the origin proved. Whether that
        criterion passed - so the repair never re-checks it - or is carried forward,
        deleting the file regresses the requirement, and preservation is what says so.
        """
        (self.root / "kept.ts").write_text("export const kept = 1;\n", encoding="utf-8")
        (self.root / "incidental.ts").write_text("export const scratch = 1;\n", encoding="utf-8")
        acceptance = [
            {"criterion_id": "kept", "description": "Proven module preserved.", "evaluator": {"type": "paths_exist", "paths": ["kept.ts"]}, "last_status": "passed"},
            {"criterion_id": "feature", "description": "Feature module exists.", "evaluator": {"type": "paths_exist", "paths": ["feature.ts"]}},
        ]
        origin_id = await self._seed_failed_task("Proven and outstanding", ["kept.ts", "incidental.ts"], acceptance)
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = json.loads(repair.acceptance_json)
        by_id = {item["criterion_id"]: item for item in criteria}
        self.assertEqual(by_id[f"{key}:files"]["evaluator"]["paths"], ["kept.ts"], "Measured origin work is preserved; scratch output is not.")
        preservation = [by_id[f"{key}:files"]]
        (self.root / "incidental.ts").unlink()
        self.assertEqual([item["status"] for item in WorkspaceAcceptanceService().evaluate(self.root, preservation, [{"path": "incidental.ts", "change": "deleted"}])], ["passed"], "Dropping an unmeasured file is the repair's business.")
        (self.root / "kept.ts").unlink()
        self.assertEqual([item["status"] for item in WorkspaceAcceptanceService().evaluate(self.root, preservation, [{"path": "kept.ts", "change": "deleted"}])], ["failed"], "Deleting proven work is a regression, whatever else the repair achieves.")
        self.assertIn(
            "may be completed, moved into the measured paths, or removed",
            repair.description,
            "The executor has to be told which changes are its own to move: the unstated version produced a re-export shim.",
        )

    async def test_repair_scope_includes_reachable_shell_for_unreachable_surface(self):
        # An interrupted attempt built a data-backed screen but never wired it into
        # the app. Its repair carries the origin's `deliverable_surface`, which
        # requires the screen be reachable from an entry point - established only by
        # importing it from a module already on the reachable graph (App.tsx). That
        # ancestor is neither a changed file nor named by any criterion, so unless the
        # merged scope adds the reachable shell the contract demands an edit the scope
        # forbids and can never pass.
        (self.root / "frontend" / "src" / "pages").mkdir(parents=True)
        (self.root / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "main.tsx").write_text(
            'import App from "./App";\nimport { createRoot } from "react-dom/client";\n'
            'createRoot(document.getElementById("root")!).render(<App />);\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "App.tsx").write_text(
            'import { useState } from "react";\n'
            'export default function App() {\n  const [tab] = useState("home");\n'
            '  return <main>{tab}</main>;\n}\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "pages" / "DashboardPage.tsx").write_text(
            'import { useEffect, useState } from "react";\n'
            'export default function DashboardPage() {\n'
            '  const [metrics, setMetrics] = useState<Record<string, number>>({});\n'
            '  useEffect(() => { fetch("/api/dashboard").then((r) => r.json()).then(setMetrics); }, []);\n'
            '  return <section>{Object.entries(metrics).map(([k, v]) => <p key={k}>{k}: {v}</p>)}</section>;\n}\n',
            encoding="utf-8")

        surface = {"criterion_id": "screen", "description": "Data-backed dashboard renders /api/dashboard.",
                   "evaluator": {"type": "deliverable_surface", "path": "frontend/src/pages/DashboardPage.tsx", "min_chars": 120, "required_any": ["/api/dashboard"]}}
        origin_id = await self._seed_failed_task(
            "Data-backed dashboard analytics", ["frontend/src/pages/DashboardPage.tsx"], [surface])
        result = await self._reconcile()
        self.assertEqual(len(result["tasks_created"]), 1)
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = {item["criterion_id"]: item for item in json.loads(repair.acceptance_json)}
        scope = criteria[f"{key}:scope"]["evaluator"]["paths"]
        # The wiring ancestor and the entry point - the reachable shell - are now in
        # scope, so the executor can import the screen and satisfy reachability.
        self.assertIn("frontend/src/App.tsx", scope)
        self.assertIn("frontend/src/main.tsx", scope)
        # Still bounded to the surface itself and the reachability-bearing criterion.
        self.assertIn("frontend/src/pages/DashboardPage.tsx", scope)
        self.assertEqual(criteria[f"{key}:origin:screen"]["evaluator"]["type"], "deliverable_surface")

    async def test_repair_scope_unchanged_when_surface_reachability_disabled(self):
        # The widening is targeted: a surface that opts out of the reachability walk
        # (require_reachable=False) needs no wiring ancestor, so its repair scope stays
        # exactly the interrupted changes plus the origin's named paths.
        (self.root / "frontend" / "src").mkdir(parents=True)
        (self.root / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "main.tsx").write_text('import App from "./App";\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "App.tsx").write_text('export default function App() { return null; }\n', encoding="utf-8")
        (self.root / "frontend" / "src" / "widget.tsx").write_text(
            'export function widget() { return fetch("/api/widget"); }\n', encoding="utf-8")
        surface = {"criterion_id": "widget", "description": "Widget module holds real content.",
                   "evaluator": {"type": "deliverable_surface", "path": "frontend/src/widget.tsx", "min_chars": 5000, "required_any": ["/api/widget"], "require_reachable": False}}
        origin_id = await self._seed_failed_task("Widget module", ["frontend/src/widget.tsx"], [surface])
        result = await self._reconcile()
        self.assertEqual(len(result["tasks_created"]), 1)
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        key = f"partial:{origin_id}"
        criteria = {item["criterion_id"]: item for item in json.loads(repair.acceptance_json)}
        scope = criteria[f"{key}:scope"]["evaluator"]["paths"]
        self.assertEqual(scope, ["frontend/src/widget.tsx"])
        self.assertNotIn("frontend/src/App.tsx", scope)

    async def test_repair_chain_stays_anchored_to_the_origin_task(self):
        acceptance = [{"criterion_id": "feature", "description": "Feature present.", "evaluator": {"type": "paths_exist", "paths": ["service.ts"]}}]
        origin_id = await self._seed_failed_task("Partial feature", ["service.ts"], acceptance)
        key = f"partial:{origin_id}"
        await self._seed_failed_task(
            "Repair incomplete work: Partial feature", ["service.ts"], acceptance,
            context_refs=[{"source_type": "completeness_reconciliation", "dedupe_key": key, "origin_task_id": origin_id, "parent_task_id": origin_id}],
        )
        result = await self._reconcile()
        self.assertEqual(len(result["tasks_created"]), 1)
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
        refs = json.loads(repair.context_refs_json)
        self.assertEqual(repair.title, "Repair incomplete work: Partial feature")
        self.assertTrue(any(ref.get("dedupe_key") == key and ref.get("origin_task_id") == origin_id for ref in refs))

    async def test_repair_generation_cap_stops_cloning_the_same_anchor(self):
        acceptance = [{"criterion_id": "feature", "description": "Feature present.", "evaluator": {"type": "paths_exist", "paths": ["service.ts"]}}]
        origin_id = await self._seed_failed_task("Partial feature", ["service.ts"], acceptance)
        key = f"partial:{origin_id}"
        refs = [{"source_type": "completeness_reconciliation", "dedupe_key": key, "origin_task_id": origin_id, "parent_task_id": origin_id}]
        for _ in range(3):
            await self._seed_failed_task("Repair incomplete work: Partial feature", ["service.ts"], acceptance, context_refs=refs)
        result = await self._reconcile()
        self.assertEqual(result["tasks_created"], [])

    async def test_completed_repair_stops_new_generations_for_failed_origin(self):
        acceptance = [{"criterion_id": "feature", "description": "Feature present.", "evaluator": {"type": "paths_exist", "paths": ["service.ts"]}}]
        origin_id = await self._seed_failed_task("Partial feature", ["service.ts"], acceptance)
        key = f"partial:{origin_id}"
        await self._seed_failed_task(
            "Repair incomplete work: Partial feature", ["service.ts"], acceptance, state="completed",
            context_refs=[{"source_type": "completeness_reconciliation", "dedupe_key": key, "origin_task_id": origin_id, "parent_task_id": origin_id}],
        )
        result = await self._reconcile()
        self.assertEqual(result["tasks_created"], [])

    async def test_cancelled_repair_is_not_recreated_on_the_next_pass(self):
        # Retiring a repair is a decision that its carried-forward contract must not
        # be retried, either because it cannot prove work or because it contradicts
        # the project's real structure. Recreating it reinstated the same contract on
        # the next pass, so retirement never stuck and the retire/recreate pair
        # looped forever.
        acceptance = [{"criterion_id": "feature", "description": "Feature present.", "evaluator": {"type": "path_exists_contains", "path": "service.ts", "contains": ["def handle"]}}]
        origin_id = await self._seed_failed_task("Partial feature", ["service.ts"], acceptance)
        key = f"partial:{origin_id}"
        await self._seed_failed_task(
            "Repair incomplete work: Partial feature", ["service.ts"], acceptance, state="cancelled",
            context_refs=[{"source_type": "completeness_reconciliation", "dedupe_key": key, "origin_task_id": origin_id, "parent_task_id": origin_id}],
        )
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            repairs = (await session.execute(select(OrchestrationTaskRecord).where(
                OrchestrationTaskRecord.project_id == self.project_id,
                OrchestrationTaskRecord.title == "Repair incomplete work: Partial feature",
            ))).scalars().all()
        self.assertEqual(result["tasks_created"], [])
        self.assertEqual([task.state for task in repairs], ["cancelled"])

    async def test_single_pass_creates_one_live_task_per_requirement(self):
        requirement_id = await self._requirement()
        # The interrupted task carried the requirement's own contract, so the repair
        # re-proves it and no second task is needed for the same requirement.
        acceptance = [{"criterion_id": "feature", "description": "Customers UI exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}}]
        await self._seed_failed_task("Implement customer workflow", ["src/customers.ts"], acceptance, requirement_ids=[requirement_id])
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        live = [task for task in tasks if task.state in {"planned", "ready", "running"} and requirement_id in json.loads(task.requirement_ids_json)]
        self.assertEqual(len(result["tasks_created"]), 1)
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].title, "Repair incomplete work: Implement customer workflow")
        self.assertEqual(result["ready_queue"], [live[0].id])

    async def test_live_task_naming_a_requirement_without_its_contract_does_not_suppress_it(self):
        # A legacy task can list several requirements while its acceptance checks a
        # single surface. Treating the reference as coverage left those requirements
        # with no verifiable contract queued anywhere, so the loop never converged.
        requirement_id = await self._requirement()
        partial_id = f"task-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(
                id=partial_id, project_id=self.project_id, task_type="implementation", title="Complete required application surface",
                requirement_ids_json=json.dumps([requirement_id]),
                acceptance_json=json.dumps([{"criterion_id": "surface", "description": "Surface exists.", "evaluator": {"type": "paths_exist", "paths": ["src/App.tsx"]}}]),
                state="planned",
            ))
            await session.commit()
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            created = [await session.get(OrchestrationTaskRecord, task_id) for task_id in result["tasks_created"]]
        titles = [task.title for task in created]
        self.assertEqual(titles, ["Complete requirement: Customer workflow"])
        self.assertEqual(
            json.loads(created[0].acceptance_json)[0]["evaluator"],
            {"type": "paths_exist", "paths": ["src/customers.ts"]},
        )

    async def _partially_satisfied_requirement(self):
        """Seed a requirement whose first criterion already passes and whose rest do not."""
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "shell.ts").write_text("export const shell = true;\n", encoding="utf-8")
        satisfied = {"criterion_id": "shell", "description": "Shell exists.", "evaluator": {"type": "paths_exist", "paths": ["src/shell.ts"]}}
        routes = {"criterion_id": "routes", "description": "Routing exists.", "evaluator": {"type": "paths_exist", "paths": ["src/routes.ts"]}}
        orders = {"criterion_id": "orders", "description": "Orders view exists.", "evaluator": {"type": "paths_exist", "paths": ["src/orders.ts"]}}
        requirement_id = await self._requirement(acceptance=[satisfied, routes, orders])
        return requirement_id, satisfied, routes, orders

    async def _seed_live_task(self, requirement_id, acceptance, title="Repair incomplete work: application shell"):
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(
                id=task_id, project_id=self.project_id, task_type="implementation", title=title,
                requirement_ids_json=json.dumps([requirement_id]), acceptance_json=json.dumps(acceptance),
                context_refs_json="[]", state="planned",
            ))
            await session.commit()
        return task_id

    async def _live_task_ids(self, requirement_id):
        async with AsyncSessionLocal() as session:
            tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
        return [
            task.id for task in tasks
            if task.state in {"planned", "ready", "running"} and requirement_id in json.loads(task.requirement_ids_json)
        ]

    async def test_live_task_covering_the_still_failing_criteria_suppresses_a_duplicate(self):
        # A repair carries forward only the part of the contract that does not hold
        # yet, so demanding the full evaluator set read a repair as partial coverage
        # and queued a second task for the same requirement: task-b727f1f403d0 and
        # task-bb3439579748 were both live for one shell requirement, both editing
        # App.tsx. Coverage is about the outstanding contract, not the whole one.
        requirement_id, _satisfied, routes, orders = await self._partially_satisfied_requirement()
        live_id = await self._seed_live_task(requirement_id, [routes, orders])
        result = await self._reconcile()
        self.assertEqual(await self._live_task_ids(requirement_id), [live_id])
        self.assertEqual(result["tasks_created"], [])

    async def test_live_task_missing_a_failing_criterion_still_does_not_suppress_it(self):
        # The converse guard: discounting satisfied criteria must not let partial
        # coverage pass for the whole outstanding contract. The narrow task never
        # proves the orders view, so the fresh task has to carry what it leaves out -
        # and once it does, the narrow task's remaining work is entirely inside it.
        requirement_id, satisfied, routes, orders = await self._partially_satisfied_requirement()
        narrow_id = await self._seed_live_task(requirement_id, [satisfied, routes])
        result = await self._reconcile()
        self.assertEqual(len(result["tasks_created"]), 1)
        async with AsyncSessionLocal() as session:
            created = await session.get(OrchestrationTaskRecord, result["tasks_created"][0])
            superseded = await session.get(OrchestrationTaskRecord, narrow_id)
        self.assertIn(orders["evaluator"], [item["evaluator"] for item in json.loads(created.acceptance_json)])
        self.assertEqual(superseded.state, "cancelled")
        self.assertEqual(await self._live_task_ids(requirement_id), [created.id])

    async def test_duplicate_already_in_the_graph_is_retired_in_favour_of_the_wider_contract(self):
        # Suppressing duplicate creation does not heal a graph polluted before the
        # fix landed. Two queued tasks rewriting the same surface mean whichever ran
        # second would undo the first, so reconciliation retires the narrower one.
        #
        # Which of the two is the narrower one has to follow from what they assert.
        # This seeded a pair whose three criteria evaluated the identical three paths
        # under different criterion_ids - equal on acceptance count, on outstanding
        # count, and (within the platform clock's resolution) on creation time - so
        # the survivor was settled by which random task id sorted first and the
        # assertion naming one of them held by luck. Observed failing 2026-08-21 in
        # the full suite, on a run where the coin landed the other way. The wider
        # task now carries an assertion the narrower one does not, which is the only
        # thing that makes it wider, and the survivor still has to prove everything
        # the retired task did.
        requirement_id, satisfied, routes, orders = await self._partially_satisfied_requirement()
        styles = {"criterion_id": "styles", "description": "Theme exists.", "evaluator": {"type": "paths_exist", "paths": ["src/theme.css"]}}
        wide_id = await self._seed_live_task(requirement_id, [satisfied, styles, routes, orders], title="Repair incomplete work: application shell")
        narrow_id = await self._seed_live_task(requirement_id, [satisfied, routes, orders], title="Complete requirement: Customer workflow")
        result = await self._reconcile()
        async with AsyncSessionLocal() as session:
            retired = await session.get(OrchestrationTaskRecord, narrow_id)
            kept = await session.get(OrchestrationTaskRecord, wide_id)
        evaluators = [item["evaluator"] for item in json.loads(kept.acceptance_json)]
        self.assertEqual(await self._live_task_ids(requirement_id), [wide_id])
        self.assertEqual(result["tasks_created"], [])
        self.assertEqual(retired.state, "cancelled")
        self.assertIn(satisfied["evaluator"], evaluators, "Retiring the narrower task may not drop what it asserted.")
        self.assertIn(styles["evaluator"], evaluators)

    async def test_live_tasks_with_different_outstanding_contracts_both_survive(self):
        # Retirement must not collapse genuinely different work. Both tasks carry the
        # requirement's whole outstanding contract, so nothing fresh is queued, but
        # each also has outstanding work the other never proves.
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        routes = {"criterion_id": "routes", "description": "Routing exists.", "evaluator": {"type": "paths_exist", "paths": ["src/routes.ts"]}}
        orders = {"criterion_id": "orders", "description": "Orders view exists.", "evaluator": {"type": "paths_exist", "paths": ["src/orders.ts"]}}
        activity = {"criterion_id": "activity", "description": "Activity view exists.", "evaluator": {"type": "paths_exist", "paths": ["src/activity.ts"]}}
        requirement_id = await self._requirement(acceptance=[routes])
        first = await self._seed_live_task(requirement_id, [routes, orders], title="Complete requirement: routing and orders")
        second = await self._seed_live_task(requirement_id, [routes, activity], title="Complete requirement: routing and activity")
        result = await self._reconcile()
        self.assertEqual(result["tasks_created"], [])
        self.assertEqual(sorted(await self._live_task_ids(requirement_id)), sorted([first, second]))


    async def test_duplicate_list_entry_never_retires_a_task_in_favour_of_itself(self):
        # `_task` returns the existing live task when a dedupe key already has one, so
        # the caller's list holds that record twice. Positional exclusion then let the
        # second entry treat the first as a keeper, and one pass cancelled every repair
        # in the NEXA graph - each in favour of itself.
        requirement_id, _satisfied, routes, orders = await self._partially_satisfied_requirement()
        task_id = await self._seed_live_task(requirement_id, [routes, orders])
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, task_id)
            findings = await CompletenessReconciliationService()._retire_redundant(session, self.project_id, self.root, [task, task])
            await session.commit()
            task = await session.get(OrchestrationTaskRecord, task_id)
        self.assertEqual(findings, [])
        self.assertEqual(task.state, "planned")

    async def test_a_repair_is_never_retired_for_redundancy(self):
        # A repair is anchored to preserved partial work and `_repair_capacity` reads
        # its cancellation as a decision never to retry that anchor, so retiring one
        # here would silently close it even though the wider task carries no
        # preservation criterion.
        requirement_id, _satisfied, routes, orders = await self._partially_satisfied_requirement()
        activity = {"criterion_id": "activity", "description": "Activity view exists.", "evaluator": {"type": "paths_exist", "paths": ["src/activity.ts"]}}
        repair_id = await self._seed_live_task(requirement_id, [routes, orders])
        wider_id = await self._seed_live_task(requirement_id, [routes, orders, activity], title="Complete requirement: Customer workflow")
        async with AsyncSessionLocal() as session:
            repair = await session.get(OrchestrationTaskRecord, repair_id)
            repair.context_refs_json = json.dumps([{"source_type": "completeness_reconciliation", "dedupe_key": "partial:task-origin"}])
            await session.commit()
            await CompletenessReconciliationService()._retire_redundant(session, self.project_id, self.root, [repair, await session.get(OrchestrationTaskRecord, wider_id)])
            await session.commit()
        self.assertEqual(sorted(await self._live_task_ids(requirement_id)), sorted([repair_id, wider_id]))

    def test_redundancy_retirement_leaves_the_repair_anchor_open(self):
        # Retiring a repair because another live task covered the same outstanding
        # work is bookkeeping, not a decision that the anchor must never be retried.
        # Reading it as one left the preserved partial work with nothing queued.
        key = "partial:task-origin"
        cancelled = OrchestrationTaskRecord(
            id="task-repair", project_id=self.project_id, task_type="implementation", title="Repair",
            requirement_ids_json="[]", acceptance_json="[]", state="cancelled",
            context_refs_json=json.dumps([{"source_type": "completeness_reconciliation", "dedupe_key": key}]),
        )
        service = CompletenessReconciliationService()
        self.assertFalse(service._repair_capacity([cancelled], key))
        self.assertTrue(service._repair_capacity([cancelled], key, {"task-repair"}))


if __name__ == "__main__":
    unittest.main()
