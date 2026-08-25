"""Defect #75: a task resting in `blocked` was counted as live and blocked delivery forever.

`project_dispatcher` chooses between exactly two resting states when a run ends without
meeting its contract: `failed` if the process failed or timed out, `blocked` if the
process completed and acceptance fell short. The second is the ordinary outcome of a
partial delivery, and it was the one `_settlement` did not test - #71 gave `failed` the
supersession test and left `blocked` in `LIVE_TASK_STATES`, so every partial delivery
reported `settled: False, reason: "live"` for the rest of the project's life.

Nothing can clear it. `task_graph` builds the ready queue from `state == "planned"` and
nothing else, so a blocked task is never dispatched again; the `blocked -> planned` edges
in `project_dispatcher` are immediate pairs inside a single code path, a requeue idiom
standing in for the illegal `ready -> planned`, never a rescue of a task at rest.

These tests hold both halves of the fix: a blocked task becomes eligible for supersession,
and it stops supplying coverage to anything else at the same moment. The second half is
what keeps the first from being a hole - two blocked tasks against one requirement would
otherwise settle each other while nothing was queued for the work.
"""
import json
import unittest
import uuid

from sqlalchemy import delete, select

from core.ai_fleet.services.definition_of_done import (
    LIVE_TASK_STATES,
    SUPERSEDABLE_TASK_STATES,
    DefinitionOfDoneService,
)
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import (
    OrchestrationTaskRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    RunAttemptRecord,
    TaskRun,
)


class BlockedAtRestSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:8]
        self.project_id = f"dod75-project-{suffix}"
        self.service = DefinitionOfDoneService()
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Blocked at rest", slug=f"dod75-{suffix}", project_type="business_system", owner="local"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            run_ids = (await session.execute(select(TaskRun.id).where(TaskRun.project_id == self.project_id))).scalars().all()
            if run_ids:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(run_ids)))
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == self.project_id))
            if run_ids:
                await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
            await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.project_id == self.project_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id))
            await session.commit()

    async def _requirement(self, status="approved"):
        record = ProjectRequirementRecord(
            id=f"requirement-{uuid.uuid4().hex[:8]}", project_id=self.project_id, title="Role authorization",
            description="Guard destructive routes", requirement_type="functional", source_type="user",
            truth_state="confirmed", priority="must", status=status,
            acceptance_json=json.dumps([{"criterion_id": "guards", "description": "Routes are guarded.", "evaluator": {"type": "paths_exist", "paths": ["backend/src/routes/orders.ts"]}}]),
            evidence_json="[]",
        )
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
        return record.id

    async def _task(self, *, state, requirement_ids=(), with_run=True):
        """A task that came to rest the way the dispatcher leaves one.

        A blocked task always has a run: it got there by completing a process. The run and
        attempt are recorded as completed because that is exactly the situation - the
        process succeeded and the contract did not - and it is what makes `done` False on
        the criteria alone rather than on a missing run.
        """
        suffix = uuid.uuid4().hex[:8]
        task_id, run_id, attempt_id = f"task-{suffix}", f"run-{suffix}", f"attempt-{suffix}"
        acceptance = [{"criterion_id": "guards", "description": "Routes are guarded.", "evaluator": {"type": "path_exists_contains", "path": "backend/src/routes/orders.ts", "contains": ["requireRole"]}, "severity": "high"}]
        async with AsyncSessionLocal() as session:
            if with_run:
                session.add(TaskRun(id=run_id, prompt="Guard the destructive routes", project_id=self.project_id, status="completed"))
                session.add(RunAttemptRecord(
                    id=attempt_id, run_id=run_id, attempt_number=1, executor_type="cli", status="completed",
                    receipt_json=json.dumps({"outcome": "completed", "acceptance": [{"criterion_id": "guards", "status": "failed", "evidence": {"missing": ["requireRole"]}}]}),
                ))
            session.add(OrchestrationTaskRecord(
                id=task_id, project_id=self.project_id, task_type="implementation",
                title="Complete requirement: Backend-enforced role authorization",
                description="Guard the destructive routes", requirement_ids_json=json.dumps(list(requirement_ids)),
                dependency_ids_json="[]", acceptance_json=json.dumps(acceptance), context_refs_json="[]",
                executor_needs_json=json.dumps({"capabilities": ["coding"]}), state=state,
                current_run_id=run_id if with_run else None,
            ))
            await session.commit()
        return task_id

    async def _assess(self, task_id):
        async with AsyncSessionLocal() as session:
            return await self.service.assess(session, task_id)

    async def test_the_two_state_sets_are_disjoint_and_exclude_blocked_from_live(self):
        """The shape of the fix, so a later edit cannot quietly undo it.

        A state that can still run must never also be supersedable: it would be settled by
        a sibling while remaining queued to do the work itself, and the requirement would
        drop out of the assessment while an executor was still being asked for it.
        """
        self.assertEqual(LIVE_TASK_STATES, {"planned", "ready", "running"})
        self.assertEqual(SUPERSEDABLE_TASK_STATES, {"failed", "blocked"})
        self.assertEqual(LIVE_TASK_STATES & SUPERSEDABLE_TASK_STATES, set())

    async def test_live_means_the_same_thing_here_as_in_the_module_that_owns_queueing(self):
        """The disagreement that was the defect.

        `completeness_reconciliation` decides what is queued; this module decides what
        blocks delivery. When they disagreed about which states are live, a state the
        queue would never serve was still counted as work in progress.
        """
        from core.ai_fleet.services import completeness_reconciliation

        self.assertEqual(LIVE_TASK_STATES, completeness_reconciliation.LIVE_TASK_STATES)

    async def test_a_blocked_task_blocks_while_nothing_carries_its_requirement(self):
        """The invariant first: a shortfall does not settle by being old.

        This is the half that must not break. A blocked task is a real shortfall against a
        real requirement, and until something that can run carries it, delivery is
        genuinely not ready and has to say so.
        """
        requirement_id = await self._requirement()
        blocked_id = await self._task(state="blocked", requirement_ids=[requirement_id])

        assessment = await self._assess(blocked_id)

        self.assertFalse(assessment["settled"], "Nothing else carries the requirement yet.")
        self.assertEqual(assessment["settlement"]["reason"], "shortfall_uncovered")
        self.assertEqual(assessment["settlement"]["uncovered_requirement_ids"], [requirement_id])
        self.assertFalse(assessment["done"], "Its acceptance measured failed; a shortfall is not an achievement.")

    async def test_a_blocked_task_is_superseded_once_a_runnable_task_carries_it(self):
        """And the half the defect removed: the repair that replaced it settles it.

        Reconciliation answers a partial delivery by queueing a repair task against the
        same requirement. The blocked origin cannot run again, so counting it as well
        reports one piece of outstanding work twice - once against the row that will do it
        and once against the row that never can.
        """
        requirement_id = await self._requirement()
        blocked_id = await self._task(state="blocked", requirement_ids=[requirement_id])
        self.assertFalse((await self._assess(blocked_id))["settled"])

        repair_id = await self._task(state="planned", requirement_ids=[requirement_id], with_run=False)

        settled = await self._assess(blocked_id)
        self.assertTrue(settled["settled"])
        self.assertEqual(settled["settlement"]["reason"], "superseded")
        self.assertEqual(settled["settlement"]["covered"][0]["ground"], "live_task")
        self.assertEqual(settled["settlement"]["covered"][0]["task_id"], repair_id)
        # Counted exactly once: the repair is now the outstanding work.
        self.assertFalse((await self._assess(repair_id))["settled"])

    async def test_a_blocked_task_is_superseded_by_its_requirement_being_settled(self):
        """The other ground for coverage applies unchanged.

        A requirement that is completed or waived needs no task at all, so a shortfall
        against it is no longer outstanding work.
        """
        requirement_id = await self._requirement(status="completed")
        blocked_id = await self._task(state="blocked", requirement_ids=[requirement_id])

        assessment = await self._assess(blocked_id)

        self.assertTrue(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "superseded")
        self.assertEqual(assessment["settlement"]["covered"][0]["ground"], "requirement_settled")

    async def test_two_blocked_tasks_on_one_requirement_do_not_settle_each_other(self):
        """The hole the narrowing of `LIVE_TASK_STATES` closes.

        Making `blocked` supersedable without removing it from the coverage set would let
        each of a pair vouch for the other while neither can run and nothing is queued -
        the requirement silently leaves the assessment. Nine of the ten requirements on
        project-23a514f0c426 had two or more blocked tasks against them, so this is the
        ordinary case rather than a corner of one.
        """
        requirement_id = await self._requirement()
        first = await self._task(state="blocked", requirement_ids=[requirement_id])
        second = await self._task(state="blocked", requirement_ids=[requirement_id])

        for task_id in (first, second):
            assessment = await self._assess(task_id)
            self.assertFalse(assessment["settled"], "A task that cannot run cannot vouch for one that cannot run.")
            self.assertEqual(assessment["settlement"]["reason"], "shortfall_uncovered")
            self.assertEqual(assessment["settlement"]["uncovered_requirement_ids"], [requirement_id])

    async def test_a_blocked_task_no_longer_covers_a_failed_one(self):
        """The narrowing applies to the case #71 already handled, and must.

        A failure whose requirement is carried only by a blocked task is not carried at
        all. Reporting it settled would retire both rows for work no row can do.
        """
        requirement_id = await self._requirement()
        blocked_id = await self._task(state="blocked", requirement_ids=[requirement_id])
        failed_id = await self._task(state="failed", requirement_ids=[requirement_id])

        failed = await self._assess(failed_id)
        self.assertFalse(failed["settled"])
        self.assertEqual(failed["settlement"]["reason"], "failure_uncovered")
        # Named for what came to rest: the same shape of shortfall, two different events.
        self.assertEqual((await self._assess(blocked_id))["settlement"]["reason"], "shortfall_uncovered")

    async def test_a_blocked_task_carrying_no_requirement_is_superseded_by_its_finding(self):
        """Parity with `failed` on the no-requirement path.

        A task filed against something other than a requirement - a broken artifact, say -
        is held by a finding that reconciliation re-measures every pass, and that finding
        blocks under `needs`. Blocking on the task as well double-counts it.
        """
        blocked_id = await self._task(state="blocked", requirement_ids=[])

        assessment = await self._assess(blocked_id)

        self.assertTrue(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "superseded")
        self.assertEqual(assessment["settlement"]["covered"], [])

    async def test_a_blocked_task_naming_a_requirement_that_does_not_exist_still_blocks(self):
        """A dangling reference resolves to nothing, and nothing carries nothing."""
        blocked_id = await self._task(state="blocked", requirement_ids=["requirement-does-not-exist"])

        assessment = await self._assess(blocked_id)

        self.assertFalse(assessment["settled"])
        self.assertEqual(assessment["settlement"]["uncovered_requirement_ids"], ["requirement-does-not-exist"])

    async def test_a_running_task_is_still_live_and_never_supersedable(self):
        """The states that can run keep reporting themselves as outstanding work.

        `running` is the sharp case: a sibling must not settle a task whose executor is
        working right now, because settling it would drop the requirement from the
        assessment while the run is still being paid for.
        """
        requirement_id = await self._requirement()
        await self._task(state="planned", requirement_ids=[requirement_id], with_run=False)
        running_id = await self._task(state="running", requirement_ids=[requirement_id])

        assessment = await self._assess(running_id)

        self.assertFalse(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "live")

    async def test_a_completed_task_is_still_not_retired_rather_than_superseded(self):
        """Completion is answered by `done`, not by settlement, and stays that way.

        A completed task that met its contract leaves the assessment through `done`; one
        that did not is a contradiction worth surfacing, not a shortfall to supersede. So
        `completed` belongs to neither set and reports the third reason.
        """
        requirement_id = await self._requirement()
        completed_id = await self._task(state="completed", requirement_ids=[requirement_id])

        assessment = await self._assess(completed_id)

        self.assertFalse(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "not_retired")

    async def test_a_cancelled_task_is_still_retired_without_a_coverage_test(self):
        """Retirement is terminal and unconditional; #71's ground is untouched."""
        requirement_id = await self._requirement()
        cancelled_id = await self._task(state="cancelled", requirement_ids=[requirement_id], with_run=False)

        assessment = await self._assess(cancelled_id)

        self.assertTrue(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "retired")
