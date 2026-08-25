import json
import unittest
import uuid

from sqlalchemy import delete, select

from core.ai_fleet.services.completion_assessment import CompletionAssessmentService
from core.ai_fleet.services.definition_of_done import DefinitionOfDoneService
from core.ai_fleet.services.quality_workspace import QualityWorkspaceService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import (
    AcceptanceCriterionRecord,
    OrchestrationTaskRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    RunAttemptRecord,
    TaskRun,
)


class DefinitionOfDoneEvidenceTests(unittest.IsolatedAsyncioTestCase):
    """The two defects that made delivery unreachable however much work was proven.

    #70: the assessment read only `acceptance_criteria`, a table whose only writer is the
    manual `AcceptanceService.record` API the orchestration pipeline never calls, so every
    task in every project reported `criteria_missing` and `done` was False by construction.

    #71: the assessment never read `task.state`, so a task TEMM itself cancelled - which
    can never acquire the completed run the assessment demands - blocked delivery forever
    with no transition available that could ever clear it.
    """

    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:8]
        self.project_id = f"dod-evidence-project-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Evidence", slug=f"dod-evidence-{suffix}", project_type="business_system", owner="local"))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            task_ids = (await session.execute(select(OrchestrationTaskRecord.id).where(OrchestrationTaskRecord.project_id == self.project_id))).scalars().all()
            run_ids = (await session.execute(select(TaskRun.id).where(TaskRun.project_id == self.project_id))).scalars().all()
            if task_ids:
                await session.execute(delete(AcceptanceCriterionRecord).where(AcceptanceCriterionRecord.task_id.in_(task_ids)))
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
            id=f"requirement-{uuid.uuid4().hex[:8]}", project_id=self.project_id, title="Customer workflow",
            description="Provide customer management", requirement_type="functional", source_type="user",
            truth_state="confirmed", priority="must", status=status,
            acceptance_json=json.dumps([{"criterion_id": "workflow", "description": "Customer module exists.", "evaluator": {"type": "paths_exist", "paths": ["src/customers.ts"]}}]),
            evidence_json="[]",
        )
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
        return record.id

    async def _task(self, *, state="planned", acceptance=None, measured=None, requirement_ids=(), dependency_ids=(), run_status="completed", attempt_status="completed", with_run=True):
        """A task as the orchestration pipeline actually writes one.

        The contract goes in `acceptance_json` and the measurement goes on the attempt
        receipt's `acceptance` array. Nothing here writes `acceptance_criteria`, because
        nothing in the pipeline does.
        """
        suffix = uuid.uuid4().hex[:8]
        task_id, run_id, attempt_id = f"task-{suffix}", f"run-{suffix}", f"attempt-{suffix}"
        if acceptance is None:
            acceptance = [{"criterion_id": "tests", "description": "Tests pass.", "evaluator": {"type": "command"}, "severity": "high"}]
        async with AsyncSessionLocal() as session:
            if with_run:
                session.add(TaskRun(id=run_id, prompt="Build", project_id=self.project_id, status=run_status))
                receipt = {"outcome": run_status}
                if measured is not None:
                    receipt["acceptance"] = measured
                session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=1, executor_type="cli", status=attempt_status, receipt_json=json.dumps(receipt)))
            session.add(OrchestrationTaskRecord(
                id=task_id, project_id=self.project_id, task_type="build", title="Build",
                acceptance_json=json.dumps(acceptance), requirement_ids_json=json.dumps(list(requirement_ids)),
                dependency_ids_json=json.dumps(list(dependency_ids)), current_run_id=run_id if with_run else None, state=state,
            ))
            await session.commit()
        return task_id

    async def _assess(self, task_id):
        async with AsyncSessionLocal() as session:
            return await DefinitionOfDoneService().assess(session, task_id)

    async def test_the_contract_the_pipeline_writes_is_the_contract_that_is_measured(self):
        """#70: a task whose declared clauses are all measured passed is done.

        Before this, `criteria_missing` was reported for a task carrying a fully declared
        and fully satisfied contract, because the assessment looked only in
        `acceptance_criteria` - which held zero rows for the entire production database
        while all 121 tasks of the live project carried a populated `acceptance_json`.
        `done` was therefore False for every task that has ever existed, and no amount of
        proven work could make a project assessable.
        """
        task_id = await self._task(
            state="completed",
            acceptance=[
                {"criterion_id": "tests", "description": "Tests pass."},
                {"criterion_id": "build", "description": "Build succeeds."},
            ],
            measured=[
                {"criterion_id": "tests", "status": "passed", "evidence": {"command": "npm test", "exit_code": 0}},
                {"criterion_id": "build", "status": "passed", "evidence": {"command": "npm run build", "exit_code": 0}},
            ],
        )
        assessment = await self._assess(task_id)
        self.assertTrue(assessment["done"])
        self.assertEqual(assessment["blockers"], [])
        self.assertEqual(sorted(item["id"] for item in assessment["criteria"]), ["build", "tests"])
        self.assertEqual({item["source"] for item in assessment["criteria"]}, {"measured"})
        # The evidence travels with the criterion, so the assessment can be audited rather
        # than merely trusted.
        self.assertEqual(assessment["criteria"][0]["evidence"]["exit_code"], 0)
        self.assertFalse(assessment["agent_output_alone_sufficient"])
        self.assertEqual(assessment["assessment_version"], "1.0")

    async def test_a_declared_clause_with_no_measurement_is_not_assumed(self):
        """The absence of a measurement is not evidence of one.

        This is what keeps #70's fix from being a rubber stamp: reading the declared
        contract cannot be allowed to mean trusting it. A clause the run never measured is
        unsatisfied, and the task blocks by the name of the clause - which is also strictly
        more informative than the old blanket `criteria_missing`.
        """
        task_id = await self._task(
            acceptance=[
                {"criterion_id": "tests", "description": "Tests pass."},
                {"criterion_id": "rbac", "description": "Roles enforced."},
            ],
            measured=[{"criterion_id": "tests", "status": "passed", "evidence": {"exit_code": 0}}],
        )
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"])
        self.assertIn("criterion_unsatisfied:rbac", assessment["blockers"])
        self.assertNotIn("criterion_unsatisfied:tests", assessment["blockers"])
        self.assertNotIn("criteria_missing", assessment["blockers"])
        sources = {item["id"]: item["source"] for item in assessment["criteria"]}
        self.assertEqual(sources, {"tests": "measured", "rbac": "declared_unmeasured"})

    async def test_a_passed_clause_with_no_evidence_still_blocks(self):
        """A verdict without evidence is an assertion, and assertions do not settle a task.

        The receipt is written by the same run whose work is being judged, so `passed` with
        an empty evidence payload has to be caught here or the contract measures nothing.
        """
        task_id = await self._task(measured=[{"criterion_id": "tests", "status": "passed", "evidence": {}}])
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"])
        self.assertIn("criterion_evidence_missing:tests", assessment["blockers"])

    async def test_an_unmeasurable_clause_blocks_rather_than_disappearing(self):
        """A clause with no `criterion_id` cannot be joined, so it is named by position.

        Dropping it would silently shrink the contract, and a contract that shrinks to
        nothing satisfies itself - the exact failure the `criteria_missing` check exists to
        prevent.
        """
        task_id = await self._task(acceptance=[{"description": "Something nobody gave an id."}], measured=[])
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"])
        self.assertIn("criterion_unsatisfied:declared:0", assessment["blockers"])
        self.assertNotIn("criteria_missing", assessment["blockers"])

    async def test_a_recorded_criterion_row_stays_authoritative(self):
        """Where the manual API has been used, its rows decide - they are not merged.

        Two contracts from two authorities would leave the effective contract dependent on
        which is read first. The recorded rows win outright, so a criterion set through the
        API keeps exactly the meaning it was given.
        """
        task_id = await self._task(
            state="completed",
            acceptance=[{"criterion_id": "tests"}, {"criterion_id": "never-measured"}],
            measured=[{"criterion_id": "tests", "status": "passed", "evidence": {"exit_code": 0}}],
        )
        async with AsyncSessionLocal() as session:
            session.add(AcceptanceCriterionRecord(
                id=f"criterion-{uuid.uuid4().hex[:8]}", task_id=task_id, criterion_type="test", description="Tests",
                evaluator="unit_test", severity="high", status="passed", evidence_json=json.dumps([{"exit_code": 0}]),
            ))
            await session.commit()
        assessment = await self._assess(task_id)
        self.assertTrue(assessment["done"], "The recorded row is satisfied, and the unmeasured declared clause is not consulted.")
        self.assertEqual([item["source"] for item in assessment["criteria"]], ["recorded"])

    async def test_the_latest_attempt_that_measured_anything_is_the_verdict(self):
        """A later attempt supersedes an earlier one, but a crash is not a verdict.

        An attempt that recorded no `acceptance` array evaluated nothing, so reading it as
        a set of failures would let a crash overwrite a real measurement - which is how a
        non-measurement becomes a false record of incapacity.
        """
        suffix = uuid.uuid4().hex[:8]
        task_id, run_id = f"task-{suffix}", f"run-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="Build", project_id=self.project_id, status="completed"))
            session.add(RunAttemptRecord(id=f"attempt-{suffix}-1", run_id=run_id, attempt_number=1, executor_type="cli", status="failed",
                                        receipt_json=json.dumps({"acceptance": [{"criterion_id": "tests", "status": "failed", "evidence": {"exit_code": 1}}]})))
            session.add(RunAttemptRecord(id=f"attempt-{suffix}-2", run_id=run_id, attempt_number=2, executor_type="cli", status="completed",
                                        receipt_json=json.dumps({"acceptance": [{"criterion_id": "tests", "status": "passed", "evidence": {"exit_code": 0}}]})))
            session.add(RunAttemptRecord(id=f"attempt-{suffix}-3", run_id=run_id, attempt_number=3, executor_type="cli", status="failed",
                                        receipt_json=json.dumps({"outcome": "crashed"})))
            session.add(OrchestrationTaskRecord(id=task_id, project_id=self.project_id, task_type="build", title="Build",
                                                acceptance_json=json.dumps([{"criterion_id": "tests"}]), dependency_ids_json="[]",
                                                current_run_id=run_id, state="completed"))
            await session.commit()
        assessment = await self._assess(task_id)
        self.assertTrue(assessment["done"], "Attempt 3 measured nothing, so attempt 2 is still the verdict.")
        self.assertEqual(assessment["criteria"][0]["status"], "passed")

    async def test_a_task_with_no_contract_at_all_still_reports_criteria_missing(self):
        """The original check survives for the case it was actually written for."""
        task_id = await self._task(acceptance=[])
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"])
        self.assertIn("criteria_missing", assessment["blockers"])

    async def test_a_cancelled_task_is_retired_rather_than_blocking_forever(self):
        """#71: TEMM's own retirement decision is not a permanent delivery blocker.

        `_retire_unprovable` and `_retire_redundant` cancel tasks before they ever execute,
        and `cancelled` is terminal in the state machine, so `completed_run_missing` on such
        a task is unsatisfiable by construction. On the live project that was 31 tasks
        blocking delivery with no transition available that could ever clear them.

        `done` stays False, because a cancelled task did not meet its contract and saying
        it did would be false. `settled` is the separate question - is there outstanding
        work here - and delivery turns on that.
        """
        task_id = await self._task(state="cancelled", with_run=False)
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"], "Retirement is not achievement.")
        self.assertIn("completed_run_missing", assessment["blockers"])
        self.assertTrue(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "retired")
        self.assertEqual(assessment["task_state"], "cancelled")

    async def test_a_failed_task_is_superseded_only_once_its_requirement_is_carried(self):
        """A failure is settled by what replaces it, never by being old.

        Nothing transitions `failed` back to `planned`: reconciliation files a finding and
        queues a fresh task. So once a live task carries the same requirement, blocking on
        the failed record too counts one piece of work twice against a row that can never
        advance. Until then it blocks - which is the invariant that keeps a failure from
        vanishing.
        """
        requirement_id = await self._requirement()
        failed_id = await self._task(state="failed", requirement_ids=[requirement_id], run_status="timed_out", attempt_status="timed_out")

        uncovered = await self._assess(failed_id)
        self.assertFalse(uncovered["settled"], "Nothing else carries the requirement yet.")
        self.assertEqual(uncovered["settlement"]["reason"], "failure_uncovered")
        self.assertEqual(uncovered["settlement"]["uncovered_requirement_ids"], [requirement_id])

        replacement_id = await self._task(state="planned", requirement_ids=[requirement_id], with_run=False)
        covered = await self._assess(failed_id)
        self.assertTrue(covered["settled"])
        self.assertEqual(covered["settlement"]["reason"], "superseded")
        self.assertEqual(covered["settlement"]["covered"][0]["ground"], "live_task")
        self.assertEqual(covered["settlement"]["covered"][0]["task_id"], replacement_id)
        # And the replacement itself is outstanding work, so the requirement is still
        # represented in the assessment exactly once.
        self.assertFalse((await self._assess(replacement_id))["settled"])

    async def test_a_failure_is_superseded_by_its_requirement_being_settled(self):
        """The other ground: the requirement itself is completed or waived.

        A requirement that is settled needs no task at all, so the failed attempt at it is
        no longer outstanding work.
        """
        requirement_id = await self._requirement(status="completed")
        failed_id = await self._task(state="failed", requirement_ids=[requirement_id], run_status="failed", attempt_status="failed")
        assessment = await self._assess(failed_id)
        self.assertTrue(assessment["settled"])
        self.assertEqual(assessment["settlement"]["covered"][0]["ground"], "requirement_settled")

    async def test_a_failure_naming_a_requirement_that_does_not_exist_still_blocks(self):
        """A dangling reference resolves to nothing, and nothing does not cover anything.

        Settlement is a claim that something else carries the work; a requirement id that
        matches no record cannot support that claim, so it must block rather than pass for
        free.
        """
        failed_id = await self._task(state="failed", requirement_ids=["requirement-does-not-exist"], run_status="failed", attempt_status="failed")
        assessment = await self._assess(failed_id)
        self.assertFalse(assessment["settled"])
        self.assertEqual(assessment["settlement"]["uncovered_requirement_ids"], ["requirement-does-not-exist"])

    async def test_a_failure_is_not_superseded_by_another_failure(self):
        """Only a live task can carry a requirement forward.

        Two failed tasks on one requirement must not settle each other - that would retire
        the requirement's entire history on the strength of nothing having succeeded.
        """
        requirement_id = await self._requirement()
        first = await self._task(state="failed", requirement_ids=[requirement_id], run_status="failed", attempt_status="failed")
        second = await self._task(state="failed", requirement_ids=[requirement_id], run_status="failed", attempt_status="failed")
        self.assertFalse((await self._assess(first))["settled"])
        self.assertFalse((await self._assess(second))["settled"])

    async def test_a_live_task_is_never_settled(self):
        """Outstanding work is outstanding whatever state it is live in.

        `blocked` was in this list until defect #75 and does not belong: it is where the
        dispatcher parks a run whose process completed and whose acceptance fell short, and
        no path leads out of it - the ready queue is built from `planned` alone. Counting
        it live meant every partial delivery blocked the project permanently. It is now
        settled the same way a failure is, by something that can actually still run
        carrying its requirement, and `tests/test_settlement_blocked_at_rest.py` holds both
        halves of that.
        """
        for state in ("planned", "ready", "running"):
            with self.subTest(state=state):
                assessment = await self._assess(await self._task(state=state, with_run=False))
                self.assertFalse(assessment["settled"])
                self.assertEqual(assessment["settlement"]["reason"], "live")

    async def test_a_completed_task_must_still_earn_done_on_evidence(self):
        """`completed` is deliberately not a settlement ground.

        Settling on the state would make the state its own proof, so a task marked
        completed with an unmeasured contract would report no outstanding work. It has to
        go on blocking until the evidence exists.
        """
        task_id = await self._task(state="completed", measured=[])
        assessment = await self._assess(task_id)
        self.assertFalse(assessment["done"])
        self.assertFalse(assessment["settled"])
        self.assertEqual(assessment["settlement"]["reason"], "not_retired")
        self.assertIn("criterion_unsatisfied:tests", assessment["blockers"])

    async def test_settled_tasks_stop_blocking_delivery_and_quality(self):
        """The two gates the assessment feeds both act on settlement.

        `CompletionAssessmentService` counted every not-done task as a blocker and
        `QualityWorkspaceService` filed a high-severity finding per blocker, so between
        them the retired tasks of the live project contributed 122 task blockers and 354
        quality findings that no work could ever remove.
        """
        requirement_id = await self._requirement(status="completed")
        proven = await self._task(state="completed", measured=[{"criterion_id": "tests", "status": "passed", "evidence": {"exit_code": 0}}])
        retired = await self._task(state="cancelled", with_run=False)
        superseded = await self._task(state="failed", requirement_ids=[requirement_id], run_status="failed", attempt_status="failed")
        outstanding = await self._task(state="planned", with_run=False)

        async with AsyncSessionLocal() as session:
            quality = await QualityWorkspaceService().summary(session, self.project_id)
            assessment = await CompletionAssessmentService().assess(session, self.project_id)

        blocking_task_ids = {item["task_id"] for item in assessment["blockers"]["tasks"]}
        self.assertEqual(blocking_task_ids, {outstanding}, "Only the task with work left to do blocks.")
        quality_task_ids = {item["evidence"]["task_id"] for item in quality["blocking_findings"] if item["source"] == "task"}
        self.assertEqual(quality_task_ids, {outstanding})

        # Nothing is hidden: every task is still reported with its blockers and the ground
        # on which it was settled, so the assessment remains auditable.
        reported = {item["task_id"]: item for item in assessment["evidence"]["tasks"]}
        self.assertEqual(set(reported), {proven, retired, superseded, outstanding})
        self.assertEqual(reported[retired]["settlement"]["reason"], "retired")
        self.assertEqual(reported[superseded]["settlement"]["reason"], "superseded")
        self.assertTrue(reported[proven]["done"])
        self.assertTrue(reported[retired]["blockers"], "The retired task's unmet blockers are still visible.")

    async def test_delivery_stays_blocked_while_a_failure_is_uncovered(self):
        """The gate becomes reachable, not open.

        A project whose only remaining task is an uncovered failure is not deliverable, and
        the fix must not make it look deliverable - that would trade one falsehood for a
        worse one.
        """
        requirement_id = await self._requirement()
        await self._task(state="failed", requirement_ids=[requirement_id], run_status="failed", attempt_status="failed")
        async with AsyncSessionLocal() as session:
            assessment = await CompletionAssessmentService().assess(session, self.project_id)
        self.assertFalse(assessment["ready"])
        self.assertTrue(assessment["blockers"]["tasks"])
        self.assertTrue(assessment["blockers"]["requirements"])

    async def test_a_dependency_on_a_retired_task_still_blocks(self):
        """Settlement answers a question about delivery, not about dependencies.

        A task waiting on one that was cancelled is not ready to run, and reusing
        settlement here would let it proceed on a dependency that never produced anything.
        """
        retired = await self._task(state="cancelled", with_run=False)
        dependent = await self._task(state="planned", dependency_ids=[retired], with_run=False)
        assessment = await self._assess(dependent)
        self.assertIn("dependencies_incomplete", assessment["blockers"])


if __name__ == "__main__":
    unittest.main()
