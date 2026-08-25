import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import AcceptanceCriterionRecord, OrchestrationTaskRecord, ProjectRequirementRecord, RunAttemptRecord, TaskRun

# A task in one of these states will still run, so anything it has not proven yet is
# outstanding work - and it is the only kind of task that can carry a requirement on
# behalf of one that cannot run again.
#
# Defect #75: `blocked` was in this set. The comment that used to sit here said in as
# many words that nothing transitions `failed` or `blocked` back to `planned`, and #71
# then acted on `failed` alone, leaving every blocked task counted as live. It cannot
# run: `task_graph` builds the ready queue from `state == "planned"` and nothing else,
# and the three `blocked -> planned` transitions in `project_dispatcher` are immediate
# pairs inside one code path - a requeue idiom, because `ready -> planned` is not a legal
# edge - never a rescue of a task at rest. `completeness_reconciliation`, which owns
# queueing, already defines this same set without `blocked`; the two modules disagreed
# about what live means and the one that decides what runs is the authority.
LIVE_TASK_STATES = {"planned", "ready", "running"}
# Where a task comes to rest when its process finished without meeting its contract:
# `failed` when the process itself failed or timed out, `blocked` when it completed and
# acceptance fell short (`project_dispatcher` picks between exactly those two on that
# distinction). Neither is retired and neither can advance, so both answer to the same
# question - is this work carried by something that can still run - rather than being
# reported as outstanding forever.
SUPERSEDABLE_TASK_STATES = {"failed", "blocked"}
SETTLED_REQUIREMENT_STATUSES = {"completed", "waived"}


class DefinitionOfDoneService:
    async def assess(self, session: AsyncSession, task_id: str) -> dict:
        task = await session.get(OrchestrationTaskRecord, task_id)
        if not task:
            raise DomainError("resource_not_found", message="Task was not found.")
        dependencies = [await session.get(OrchestrationTaskRecord, item) for item in json.loads(task.dependency_ids_json)]
        criteria = await self._criteria(session, task)
        run = await session.get(TaskRun, task.current_run_id) if task.current_run_id else None
        attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == task.current_run_id))).scalars().all() if run else []
        blockers = []
        if any(not item or item.state != "completed" for item in dependencies):
            blockers.append("dependencies_incomplete")
        if not criteria:
            blockers.append("criteria_missing")
        for criterion in criteria:
            if criterion["status"] == "passed" and not criterion["evidence"]:
                blockers.append(f"criterion_evidence_missing:{criterion['id']}")
            elif criterion["status"] == "waived" and not criterion["waiver"]:
                blockers.append(f"criterion_waiver_missing:{criterion['id']}")
            elif criterion["status"] not in {"passed", "waived"}:
                blockers.append(f"criterion_unsatisfied:{criterion['id']}")
        if not run or run.status != "completed":
            blockers.append("completed_run_missing")
        if not any(attempt.status == "completed" for attempt in attempts):
            blockers.append("completed_attempt_missing")
        settlement = await self._settlement(session, task)
        return {"task_id": task_id, "done": not blockers, "settled": settlement["settled"], "settlement": settlement, "task_state": task.state, "blockers": blockers, "criteria": criteria, "dependency_ids": json.loads(task.dependency_ids_json), "run_id": task.current_run_id, "assessment_version": "1.0", "agent_output_alone_sufficient": False}

    async def _criteria(self, session: AsyncSession, task: OrchestrationTaskRecord) -> list[dict]:
        """The task's acceptance contract and the status measured against each clause.

        Defect #70: this read only `AcceptanceCriterionRecord`, whose sole writer is
        `AcceptanceService.record` - a manual per-task API the orchestration pipeline never
        calls. `SELECT COUNT(*) FROM acceptance_criteria` returned 0 for the entire
        production database while all 121 tasks of project-23a514f0c426 carried a populated
        `acceptance_json`. So `criteria_missing` was reported for every task that has ever
        existed, `done` was False unconditionally, and no project could ever be assessed
        deliverable however much work was proven.

        The contract the pipeline does write is `OrchestrationTaskRecord.acceptance_json`,
        and the measurement it does record is the `acceptance` array on the attempt receipt
        - one `{criterion_id, status, evidence}` per clause, which maps 1:1 onto the three
        checks in `assess`. Joining declared to measured on `criterion_id` across those 121
        tasks gave 86 in exact agreement with no mismatches; the other 35 had no attempt at
        all and are correctly unsatisfied.

        Recorded rows stay authoritative wherever they exist, so a criterion set through the
        API keeps its meaning and is not merged with a second contract from another
        authority. A declared clause with no measurement is unsatisfied and never assumed:
        the absence of a measurement is not evidence of one, which is what keeps agent
        output alone from ever completing a task.
        """
        recorded = (await session.execute(select(AcceptanceCriterionRecord).where(AcceptanceCriterionRecord.task_id == task.id))).scalars().all()
        if recorded:
            return [{**item.to_dict(), "source": "recorded"} for item in recorded]
        declared = json.loads(task.acceptance_json or "[]")
        if not declared:
            return []
        measured = await self._measured(session, task.current_run_id)
        criteria = []
        for index, item in enumerate(declared):
            # A clause with no id cannot be joined to a measurement, so it is named by its
            # position and left unsatisfied rather than dropped: an unmeasurable clause has
            # to block, never disappear.
            criterion_id = item.get("criterion_id") or f"declared:{index}"
            hit = measured.get(criterion_id)
            criteria.append({
                "id": criterion_id,
                "task_id": task.id,
                "criterion_type": (item.get("evaluator") or {}).get("type"),
                "description": item.get("description"),
                "evaluator": json.dumps(item.get("evaluator") or {}),
                "severity": item.get("severity") or "high",
                "evidence": (hit or {}).get("evidence") or {},
                "status": (hit or {}).get("status") or "unsatisfied",
                "waiver": None,
                "created_at": None,
                "source": "measured" if hit else "declared_unmeasured",
            })
        return criteria

    async def _measured(self, session: AsyncSession, run_id: str | None) -> dict:
        """The acceptance measurement from the latest attempt on this run that made one.

        Later attempts supersede earlier ones, so the newest is the current truth about the
        contract. An attempt that recorded no `acceptance` array measured nothing and is
        skipped rather than read as a set of failures - a crash before evaluation is not a
        verdict on the contract.
        """
        if not run_id:
            return {}
        attempts = (await session.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id).order_by(RunAttemptRecord.attempt_number.desc()))).scalars().all()
        for attempt in attempts:
            items = (json.loads(attempt.receipt_json or "{}") or {}).get("acceptance") or []
            if items:
                return {item.get("criterion_id"): item for item in items if item.get("criterion_id")}
        return {}

    async def _settlement(self, session: AsyncSession, task: OrchestrationTaskRecord) -> dict:
        """Whether this task is still outstanding work, and on what ground.

        Defect #71: `assess` never read `task.state`, so `completed_run_missing` and
        `completed_attempt_missing` were unsatisfiable for a task TEMM itself retired - a
        cancelled task with no run can never acquire one. On project-23a514f0c426 that was
        31 cancelled tasks, 30 of them retired by this engine's own `_retire_unprovable`
        and `_retire_redundant` before ever executing, plus 49 failed ones, each blocking
        delivery permanently and with no transition available that could clear it.

        `done` is deliberately left alone. A cancelled task did not meet its contract and
        reporting that it did would be false. `settled` is the separate question delivery
        actually turns on - is there outstanding work here - and it has exactly two grounds:

        `retired`: the task is cancelled. Cancellation is terminal in the state machine and
        is only ever reached by a deliberate decision, so nothing is waiting on it. Whatever
        it was for is still carried by its requirement, which goes on blocking under
        `requirements` until that requirement is completed or waived.

        `superseded`: the task came to rest without meeting its contract - `failed` or,
        after defect #75, `blocked` - and every requirement it carried is accounted for
        elsewhere: the requirement is itself settled, or a task that can still run covers
        it. Nothing transitions either state back to `planned`; reconciliation files a
        finding and queues a fresh task, so blocking on the resting record as well counts
        the same work twice against a row that can never advance.

        Defect #75: only `failed` was tested here, so a task parked in `blocked` - which is
        where `project_dispatcher` puts every run whose process completed and whose
        acceptance fell short, the ordinary outcome of a partial delivery - was reported
        `live` and blocked delivery permanently. On project-23a514f0c426 that was 30 of the
        33 blocking tasks, each already replaced by a repair task carrying the same
        requirement, and no amount of proven work could have cleared any of them.

        The other half of that fix is in `LIVE_TASK_STATES`: a blocked task stopped
        SUPPLYING coverage at the same time it became eligible to receive it. Nine of that
        project's ten requirements had two or more blocked tasks against them, so leaving
        blocked in the coverage set would have let them settle each other wholesale while
        nothing was queued for the work - the failure this whole method exists to prevent,
        arrived at from the opposite direction.

        A resting task that leaves a requirement neither settled nor covered is NOT settled
        and goes on blocking. That is the invariant this must not break: a shortfall can
        never vanish from the assessment, it can only be superseded by something that is
        actually able to carry it.
        """
        if task.state == "cancelled":
            return {"settled": True, "reason": "retired", "task_state": task.state}
        if task.state not in SUPERSEDABLE_TASK_STATES:
            return {"settled": False, "reason": "live" if task.state in LIVE_TASK_STATES else "not_retired", "task_state": task.state}
        requirement_ids = json.loads(task.requirement_ids_json or "[]")
        if not requirement_ids:
            # A task carrying no requirement was filed against something else - a broken
            # artifact, say - and that finding is re-measured on every reconciliation pass,
            # so it is the finding that holds the concern and blocks under `needs`.
            return {"settled": True, "reason": "superseded", "task_state": task.state, "covered": [], "uncovered_requirement_ids": []}
        live = (await session.execute(select(OrchestrationTaskRecord).where(
            OrchestrationTaskRecord.project_id == task.project_id,
            OrchestrationTaskRecord.state.in_(sorted(LIVE_TASK_STATES)),
            OrchestrationTaskRecord.id != task.id,
        ))).scalars().all()
        covered = []
        uncovered = []
        for requirement_id in requirement_ids:
            ground = await self._coverage(session, requirement_id, live)
            if ground is None:
                uncovered.append(requirement_id)
            else:
                covered.append({"requirement_id": requirement_id, **ground})
        if uncovered:
            # Named for what came to rest, because these strings are read as evidence: a
            # blocked task delivered something and fell short of its contract, which is
            # not the same event as a process that failed.
            reason = "failure_uncovered" if task.state == "failed" else "shortfall_uncovered"
            return {"settled": False, "reason": reason, "task_state": task.state, "covered": covered, "uncovered_requirement_ids": uncovered}
        return {"settled": True, "reason": "superseded", "task_state": task.state, "covered": covered, "uncovered_requirement_ids": []}

    async def _coverage(self, session: AsyncSession, requirement_id: str, live: list[OrchestrationTaskRecord]) -> dict | None:
        """What still accounts for this requirement, if anything.

        A requirement id that resolves to no record is not covered, so a dangling reference
        blocks rather than passing for free.
        """
        requirement = await session.get(ProjectRequirementRecord, requirement_id)
        if requirement is not None and requirement.status in SETTLED_REQUIREMENT_STATUSES:
            return {"ground": "requirement_settled", "requirement_status": requirement.status}
        for sibling in live:
            if requirement_id in json.loads(sibling.requirement_ids_json or "[]"):
                return {"ground": "live_task", "task_id": sibling.id, "task_state": sibling.state}
        return None


definition_of_done_service = DefinitionOfDoneService()
