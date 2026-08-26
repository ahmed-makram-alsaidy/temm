import json
import hashlib
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cli_invocation import build_cli_args
from ..engine.executor_profile import TEMM_EXECUTOR_AGENT, child_env as executor_child_env, credential_env_presence, decode_config_document, executor_step_budget
from ..engine.host_capacity import host_capacity, host_observation
from ..engine.process_manager import ProcessManager
from ..errors import DomainError
from ..storage.models import AgentRecord, ModelCapabilityEvidenceRecord, ModelRecord, OrchestrationCheckpointRecord, OrchestrationTaskRecord, QuotaObservationRecord, RunAttemptRecord, TaskRun, WorkspaceRecord
from .agent_assignment import AgentAssignmentService
from .context_preparation import ContextPreparationService
from .engineering_gate import EngineeringGateService
from .execution_policy import executable_availability_ttl_seconds
from .executor_capabilities import ExecutorCapabilityService
from .orchestration_recovery import OrchestrationRecoveryService
from .latency import LatencyService
from .quota import QuotaService, detect_provider_refusal
from .usage import UsageService
from .measurement import (
    MODEL_EXECUTED,
    PROVIDER_REFUSAL,
    PROVIDER_UNAVAILABLE,
    classify_measurement,
    non_measurement_hold,
    stdout_tail,
)
from .model_registry import model_registry_service
from .run_output import RunOutputService
from .runs import RunLifecycleService
from .task_graph import TaskGraphService
from .workspace_acceptance import WorkspaceAcceptanceService
from .completeness_reconciliation import CompletenessReconciliationService


# Default timeout policies by task type
TIMEOUT_POLICIES = {
    "ai_generation": 300,   # 5 min for AI authoring
    "command": 180,         # 3 min for installs/builds
    "build": 120,           # 2 min for compilation
    "test": 120,            # 2 min for test suite
    "implementation": 300,  # 5 min for AI implementation
}

# Fallback bound for task types without an explicit policy entry.
DEFAULT_TIMEOUT_SECONDS = 600

# The only task states in which work is genuinely in flight, used to keep the
# checkpoint's active list free of phantom entries. An allowlist rather than the
# terminal-state denylist it replaced, because the complement is not stable: a task
# whose attempt measured nothing returns to `planned`, and a queued task is no more
# in flight than a failed one. Read the other way round, that requeue would have
# reported the task as active for the rest of the orchestration.
IN_FLIGHT_DISPATCH_STATES = {"ready", "running"}

# Bootstrap routes remain available for installations that have not refreshed the
# external environment yet. Refreshed, verified OpenCode models are added at runtime.
CODING_MODELS = [
    {"provider": "opencode", "model": "nemotron-3.5-lightning-free", "tier": "fast", "protocol": "opencode", "reason": "Low-latency coding route"},
    {"provider": "aliyun", "model": "qwen3.7-flash", "tier": "fast", "protocol": "opencode", "reason": "Low-latency general coding route"},
    {"provider": "aliyun", "model": "qwen3-coder-plus", "tier": "strong", "protocol": "opencode", "reason": "Strong coding model with tool calling"},
    {"provider": "aliyun", "model": "qwen3.7-max", "tier": "strong", "protocol": "opencode", "reason": "Large reasoning model"},
    {"provider": "aliyun", "model": "qwen3.5-35b-a3b", "tier": "balanced", "protocol": "opencode", "reason": "Efficient coding alternative"},
]

# The capability floor every AI task needs, and the single tournament stage that
# demonstrates exactly it. Renewal re-measures this floor and nothing beyond it.
REVERIFY_CAPABILITIES = {"coding", "file_read", "file_write"}
REVERIFY_STAGE_ID = "file_write"
REVERIFY_STAGE_TIMEOUT_SECONDS = 180

# How long a route stays excluded after a provider refused it for a spent
# allowance without saying when the allowance returns. Short enough that a daily
# free tier is retried the hour it resets, long enough that a standing refusal
# costs one attempt per hour instead of one per dispatch. A provider that does
# name a retry window overrides this with the window it gave.
PROVIDER_REFUSAL_TTL_SECONDS = 3600

# How many bootstrap candidates a dispatch response names. A fleet can hold
# hundreds of never-measured routes, and listing every one buries the route that
# was actually probed under the ones that were not.
BOOTSTRAP_CONSIDERED_PREVIEW = 8

# When a renewable route is failing real work often enough that renewing it again is
# a worse bet than measuring a route never tried. A route earns renewal by having
# proved the coding floor before, but the floor is one trivial file write: a route
# can keep certifying it while timing out, producing no effect, or missing acceptance
# on every production task it is dispatched. Renewal preferred any such route over
# every never-measured route unconditionally, so a route that could certify but not
# deliver held the fleet's one probe per dispatch and no unmeasured route was ever
# reached. These bound "chronically failing on real production work": enough failed
# real-task attempts that it is a pattern rather than a blip, and a delivery rate low
# enough that an unknown route is the better bet. They gate a *preference*, never an
# exclusion - a chronic route with no alternative is still renewed, and the judgement
# is recomputed from current evidence every dispatch, so a route that starts
# delivering stops being chronic with nothing resetting its history.
CHRONIC_FAILURE_MIN_FAILURES = 5
CHRONIC_FAILURE_MAX_ACCEPTANCE_RATE = 0.34

# The context pack budget when the selected route declares no window of its own.
DEFAULT_CONTEXT_PACK_TOKENS = 32000
# Held back from a declared window for the executor's own reply, so a pack sized at
# the whole window cannot leave the model with no room to answer in.
CONTEXT_REPLY_RESERVE_TOKENS = 8000
# A derived pack budget never falls below this, whatever the prompt costs: a window
# too small to hold the prompt is a fact about the route, not a reason to prepare no
# context at all.
MIN_CONTEXT_PACK_TOKENS = 1024
# The pack's own estimator (`utf8_chars_div_4`), so the reserve is denominated in
# the same unit as the budget it is subtracted from.
PROMPT_TOKEN_DIVISOR = 4
# How many excluded sources a receipt names individually. The count is always exact;
# a repair scope of fifty files does not need fifty entries to be legible.
MAX_RECORDED_EXCLUSIONS = 20


class ProjectDispatcherService:
    def __init__(self, manager: ProcessManager):
        self.manager = manager
        self.assignment = AgentAssignmentService()
        self.context = ContextPreparationService()
        self.runs = RunLifecycleService()
        self.output = RunOutputService()
        self.recovery = OrchestrationRecoveryService()
        self.capabilities = ExecutorCapabilityService()
        self.acceptance = WorkspaceAcceptanceService()
        self.reconciliation = CompletenessReconciliationService()
        self.quota = QuotaService()
        self.usage = UsageService()
        self.latency = LatencyService()

    async def dispatch_ready(self, session: AsyncSession, project_id: str, workspace_id: str, checkpoint_id: str, token_limit: int | None = None, timeout_seconds: float | None = None, max_tasks: int = 1) -> dict:
        if not 1 <= max_tasks <= 16 or (timeout_seconds is not None and not 1 <= timeout_seconds <= 3600):
            raise DomainError("validation_failed", message="Dispatch limits are invalid.")
        checkpoint = await session.get(OrchestrationCheckpointRecord, checkpoint_id)
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not checkpoint or checkpoint.project_id != project_id or checkpoint.state not in {"approved", "running"} or not workspace:
            raise DomainError("resource_conflict", message="Approved/running orchestration checkpoint and workspace are required.")

        await self._recover_orphaned_tasks(session, project_id)

        # Recovery can return a blocked task straight to the queue without a
        # reconciliation pass, so the provability guard runs here too. Acceptance
        # decides completion, and a contract that already passes against the
        # untouched workspace would record a completion for work never done.
        retired_unprovable = await self.reconciliation.retire_unprovable_queue(session, project_id, workspace_id)

        # Derive the task graph and get the initial ready queue
        graph = await TaskGraphService().derive(session, project_id)
        ready = graph["ready_queue"][:max_tasks]
        
        # If the ready queue is empty, attempt to reconcile completeness
        if not ready:
            recon_result = await self.reconciliation.reconcile(session, project_id, workspace_id, checkpoint_id)
            # Re-derive the graph after reconciliation
            graph = await TaskGraphService().derive(session, project_id)
            ready = graph["ready_queue"][:max_tasks]
            # If still no ready tasks, return a status indicating blockers remain but no executable work could be generated
            if not ready:
                # Check if reconciliation created any findings or tasks
                if recon_result.get("findings_created") or recon_result.get("tasks_created"):
                    # We created work but it's not ready yet (e.g., dependencies not met)
                    return {
                        "project_id": project_id,
                        "checkpoint_id": checkpoint_id,
                        "status": checkpoint.state,  # Keep the current checkpoint state
                        "dispatched": [],
                        "ready_queue": graph["ready_queue"],
                        "reconciliation": recon_result,
                        "retired_unprovable": retired_unprovable,
                        "message": "Reconciliation created work but no tasks are ready yet",
                    }
                elif recon_result.get("assessment_ready"):
                    return {
                        "project_id": project_id,
                        "checkpoint_id": checkpoint_id,
                        "status": "idle",
                        "dispatched": [],
                        "ready_queue": graph["ready_queue"],
                        "retired_unprovable": retired_unprovable,
                    }
                else:
                    return {"project_id": project_id, "checkpoint_id": checkpoint_id, "status": "incomplete", "dispatched": [], "ready_queue": [], "reconciliation": recon_result, "retired_unprovable": retired_unprovable}
        
        # A route TEMM proved by execution stops being selectable the moment its
        # evidence lapses, so renew it before selection reads that evidence.
        route_refresh = await self._reverify_lapsed_routes(session, ready)

        # If we have ready tasks, set up the checkpoint for dispatching
        # Get the current active task IDs from the checkpoint
        # Drop entries left behind by earlier dispatches. Dispatch is synchronous, so
        # a task recorded as active has normally already reached a terminal state by
        # the time the checkpoint is saved; keeping those IDs made the checkpoint
        # report phantom in-flight work forever.
        active = await self._live_active_ids(session, json.loads(checkpoint.active_task_ids_json or "[]"))
        # We'll dispatch up to max_tasks tasks from the ready queue
        # These tasks will become active
        remaining = list(graph["ready_queue"])
        results = []
        for task_id in ready[:max_tasks]:
            await session.refresh(checkpoint)
            if checkpoint.state not in {"approved", "running"}:
                break
            task = await session.get(OrchestrationTaskRecord, task_id)
            task_type = task.task_type if task else "implementation"
            effective_timeout = self._effective_timeout(task_type, timeout_seconds)
            if task_type == "command":
                result = await self._dispatch_command(session, task_id, workspace, effective_timeout)
            else:
                result = await self._dispatch_ai(session, task_id, workspace, token_limit, effective_timeout)
            results.append(result)
            # Remove the dispatched task from the ready queue
            remaining = [item for item in remaining if item != task_id]
            # Record the task as active only while it is genuinely in flight.
            active = await self._live_active_ids(session, [*active, task_id])
            await session.refresh(checkpoint)
            if checkpoint.state not in {"approved", "running"}:
                break
            checkpoint = await self.recovery.save(
                session,
                project_id,
                "running",
                json.loads(checkpoint.cursor_json or {}),
                remaining,
                active,
                [],
                checkpoint.id,
                checkpoint.revision,
            )
        await session.refresh(checkpoint)
        return {
            "project_id": project_id,
            "checkpoint_id": checkpoint.id,
            "status": checkpoint.state,
            "dispatched": results,
            "ready_queue": json.loads(checkpoint.ready_queue_json or "[]"),
            "checkpoint_revision": checkpoint.revision,
            "retired_unprovable": retired_unprovable,
            **({"route_refresh": route_refresh} if route_refresh else {}),
        }

    async def _reverify_lapsed_routes(self, session: AsyncSession, ready: list[str]) -> dict | None:
        """Measure a route so selection has one: renew a proven route, or bootstrap.

        Capability evidence and executable availability both expire, and expiry is
        what stops a stale verification from being trusted indefinitely. Nothing
        renewed them, so a fleet holding a working route lost the ability to
        dispatch anything about an hour later, and the resulting
        `execution_unavailable` was only cleared by an operator running the
        tournament out of band. TEMM owns that measurement, so TEMM renews it.

        Renewal alone left a second way to reach the same dead end. A route qualified
        for renewal only when its newest execution evidence for every capability was
        positive, which is the right bound on *renewal* - a route that last ran badly
        must not be retried until something re-measures it - but it also silently
        excluded every route TEMM had never run at all. Production evidence
        2026-08-19: seven working credentials, 342 discovered coding routes, and three
        routes with any execution history whatsoever. All three were refusing or
        spent, so dispatch raised `execution_unavailable` while 339 unmeasured routes
        sat behind a gate only an operator's manual tournament could open. A fleet
        that cannot measure its own routes for the first time is not self-sufficient.

        So renewal is preferred and bootstrap is the fallback: a route TEMM has proven
        before is the better bet than one it knows nothing about, and bootstrap runs
        only when no proven route is renewable. Bootstrap carries the same bound in
        the same direction - a failed probe records the route's incapacity as its
        newest execution evidence, which withdraws it from this path for good rather
        than re-probing it every dispatch. Each probe therefore either wins a route
        or eliminates one, and one probe per dispatch is the whole cost. A probe that
        never reached the model is neither of those outcomes - it writes no evidence by
        design, leaves the route as untried as it found it, and so settles nothing about
        the choice it was spent on. `_probe_measured` is what tells the two apart.

        Preferring a proven route unconditionally left one more way to entrench a bad
        one. The floor a route proves for renewal is a single trivial file write, and a
        route can keep passing that certification while failing every real task it is
        dispatched - timing out, producing no effect, or missing acceptance. Such a
        route stayed renewable forever and, being renewable, was preferred over every
        never-measured route, so it held the one probe per dispatch and no unmeasured
        route was ever reached however many working credentials sat behind them.
        Production evidence 2026-08-20: a free route certified the floor repeatedly
        while its real-task record on this project was three accepted writes against
        twenty-three failures, sixteen of them timeouts or no-effect, and its renewal
        blocked the fleet from ever measuring a discovered coding route. So renewal is
        preferred only among routes still delivering: when every renewable route is
        chronically failing real production work and an unmeasured route exists to try,
        the probe yields to bounded exploration instead. This is a preference between a
        known-bad bet and an unknown one, never an exclusion - a chronic route with no
        unmeasured alternative is still renewed, `_chronic_production_failure` is
        recomputed from current evidence every dispatch, and the trigger and the
        production evidence that caused it are recorded on the probed route. An
        alternative whose probe measured nothing has not in fact been tried, so the
        renewal that yield deferred is taken in the same dispatch rather than a
        dispatch later - a queue does not wait on a probe that answered nothing.

        Only the coding floor is renewed, by the one stage that demonstrates it. A
        task needing more still fails selection and needs the full sweep, which is
        the honest outcome - a single file write proves nothing about dependency
        management.

        Which proven route to renew is decided by what the routes did on this project,
        not by which was proven most recently. Recency measures the last renewal rather
        than the route, so it fed itself: the route renewed last held the newest proof,
        was therefore the only available route, was therefore the only route dispatched,
        and was therefore renewed again - which kept a route that timed out on five
        consecutive NEXA tasks as the fleet's sole executor while four healthier proven
        routes stayed lapsed. Health orders the candidates and never excludes one: a
        route with a bad record is still worth renewing when it is the only proven
        route left.

        Health measures how a route performed, which says nothing about whether the
        provider will let the probe reach the model at all - and both guards that do
        hold a refusing route out are bounded, so that route comes back up for renewal
        on its own. So the first thing asked of a candidate is whether its newest
        attempt reached the provider. Production evidence 2026-08-21 22:50:58:
        `openai/gpt-5.4` keyed (0 timeouts, 3 recent failures) against
        `opencode/x-preview-f-free`'s (1, 3), won on the first key, and took the
        queue's one renewal 108 seconds after its own spent-allowance observation
        expired and 3m12s after its refusal aged out of the `_recent_refusals` window.
        Its newest provider interaction was that 429 and its floor had expired 19.5
        hours earlier, while x-preview-f-free had been certified through the production
        path 30 minutes before with a floor live for another 28. The probe re-confirmed
        the refusal in 80.2s, measured nothing, and the dispatch raised
        `execution_unavailable` with the certified route one renewal away. Re-testing a
        lapsed allowance is right - allowances do come back, and that reconfirmation
        duly doubled the horizon - but it is a different purchase from the one the
        queue is waiting on, and there is one probe to spend on them both. Only
        provider-attributable non-measurement counts, so a host failure of ours cannot
        demote the route it happened to strike, and it orders rather than excludes, so
        a refused route with no reachable alternative is still renewed.
        """
        requirements = await self._selection_requirements(session, ready)
        if not requirements:
            return None
        project_id = ""
        for task_id in ready:
            task = await session.get(OrchestrationTaskRecord, task_id)
            if task:
                # Every queued task shares the project, and a requirement was found
                # above, so a task is found here.
                project_id = task.project_id
                break
        now = datetime.utcnow()
        routes = (await session.execute(
            select(ModelRecord).where(
                ModelRecord.source_type == "external_tool",
                ModelRecord.source_uri == "opencode-cli",
                ModelRecord.lifecycle_status == "active",
                ModelRecord.is_active.is_(True),
            )
        )).scalars().all()
        exhausted = await self._exhausted_routes(session, now)
        # Read once and shared: the check for whether the queue is already served and
        # the split of what may be probed have to hold the same routes out, or one
        # decides the queue is served with a route the other has withdrawn and the
        # dispatch measures nothing while nothing runs.
        refused = await self._recent_refusals(session, now - timedelta(seconds=PROVIDER_REFUSAL_TTL_SECONDS))
        if await self._queue_already_served(session, routes, requirements, exhausted, now, refused):
            # Some queued task can already be served, so selection has a route and
            # measuring anything would only spend an executor run.
            return None
        lapsed, never_measured = await self._probe_candidates(session, routes, exhausted, now, refused)
        if lapsed:
            health = await self._route_health(session, project_id)
            turned_away = await self._provider_turned_away(session, [item[1] for item in lapsed])

            def renewal_order(candidate: tuple[datetime, str]) -> tuple:
                observed = health[candidate[1]]
                # Whether the provider let the last attempt through comes first, because
                # a probe that cannot reach the model neither wins a route nor eliminates
                # one - the currency every other bound here is priced in. Then the same
                # penalties and same cap as `rank()`, then recency as the tiebreak: among
                # routes that have performed alike, the freshest proof is the best
                # evidence that a probe will pass.
                return (candidate[1] in turned_away, min(observed["timeout_no_effect"], 3), min(observed["recent_failures"], 3), -candidate[0].timestamp())

            ordered = sorted(lapsed, key=renewal_order)
            considered = [
                {
                    "model_id": item[1],
                    "last_proven_at": item[0].isoformat(),
                    "recent_timeout_or_no_effect": health[item[1]]["timeout_no_effect"],
                    "recent_failures": health[item[1]]["recent_failures"],
                    "accepted_file_writes": health[item[1]]["accepted_writes"],
                    "failed_or_unaccepted": health[item[1]]["failed"],
                    "unmet_acceptance_contract": health[item[1]]["unmet_contract"],
                    "runs_cut_short_by_ceiling": health[item[1]]["cut_short"],
                    "undelivered_runs": max(health[item[1]]["failed"] - health[item[1]]["unmet_contract"] - health[item[1]]["cut_short"], 0),
                    "provider_turned_away_on_newest_attempt": item[1] in turned_away,
                }
                for item in ordered
            ]
            # Renewal orders by health but never excludes, so the best renewable route
            # is the least-bad one - which is still a bad bet when even it is failing
            # real production work chronically. Renew the best route that is still
            # delivering; only when none is, and an unmeasured route exists to try,
            # does the one probe per dispatch yield to bounded exploration.
            renewable = [item for item in ordered if not self._chronic_production_failure(health[item[1]])]
            if renewable:
                return await self._probe_route(session, renewable[0][1], "lapsed_execution_evidence", "project_measured_route_health", considered)
            if never_measured:
                probe = await self._bootstrap_probe(
                    session, never_measured, "chronic_renewable_failure_bootstrap",
                    self._exploration_record(ordered[0], health[ordered[0][1]], considered),
                )
                if await self._probe_measured(session, probe):
                    return probe
                # The yield asked a question of an unmeasured route and got no answer,
                # so it bought neither a won route nor an eliminated one - and the
                # deferred route is still sitting there proven. Reading the existence
                # of an unmeasured alternative as the yield's whole precondition made
                # the fallback below unreachable in exactly the case it was written
                # for: dispatch ends with no route while a route TEMM has run sits one
                # renewal away, which is the outcome that fallback exists to prevent.
                # Production evidence 2026-08-21 21:08:33: fourteen routes held a
                # positive coding floor. Eleven were held out by `opencode:aliyun`'s
                # account-wide spent-allowance observation and `openai/gpt-5.4-fast` by
                # its own model-scoped one, leaving three - `opencode/x-preview-f-free`
                # at 0 accepted writes against 5 measured failures on this project,
                # `openai/gpt-5.4` at 1 against 6, `opencode/deepseek-v4-flash-free` at
                # 3 against 23 - every one of them chronic, so renewal declined all
                # three. x-preview-f-free held a floor measured at 20:18:47 and good
                # until 21:18:47 while its executable availability had lapsed at
                # 20:48:47: a proven route made unselectable by a clock shorter than
                # its own proof. The probe went to `zai/glm-4.5`, which the provider
                # refused for a spent allowance in 78.2s (429, provider_code 1113,
                # `measured: false`). No capability evidence was written because none
                # was measured, so nothing was eliminated either, and the dispatch
                # raised `execution_unavailable` with three proven routes behind it and
                # one renewal between the queue and a run.
                #
                # So the precondition is answered by evidence rather than assumed: an
                # alternative that cannot be measured has not been tried, and the
                # probe the yield spent on it is spent on nothing. The bound stays
                # exactly as tight for the case it was written for - a probe that
                # reached the model and failed is an answer, eliminates the route, and
                # returns here unchanged. Only non-measurement reopens the choice, at
                # most once per dispatch, and it reopens it in favour of renewing the
                # route this dispatch had already ranked best among the proven.
                return {
                    **await self._probe_route(
                        session, ordered[0][1],
                        "lapsed_execution_evidence_after_unmeasurable_bootstrap",
                        "project_measured_route_health", considered,
                    ),
                    "yielded_probe": probe,
                }
            # Every renewable route is chronically failing and nothing is unmeasured:
            # renewing the least-bad chronic route still beats dispatching nothing.
            # This fallback is what makes the yield a preference and never a blacklist.
            return await self._probe_route(session, ordered[0][1], "lapsed_execution_evidence", "project_measured_route_health", considered)
        if not never_measured:
            return None
        return await self._bootstrap_probe(session, never_measured, "never_measured_route_bootstrap", None)

    @staticmethod
    def _chronic_production_failure(observed: dict) -> bool:
        """Is this route failing real work often enough to prefer an untried route?

        Read from `_route_health`, which counts only this project's own tasks. A route
        is chronic when the runs it failed to deliver are a repeated pattern rather than
        a blip (at least `CHRONIC_FAILURE_MIN_FAILURES` of them) and its delivery rate
        across those runs has fallen below `CHRONIC_FAILURE_MAX_ACCEPTANCE_RATE`.

        A run the route failed to deliver is one that ended non-zero, changed nothing,
        or ran out of clock with nothing to show for it. An acceptance shortfall is not
        one of those, and is left out of this measurement entirely - numerator and
        denominator - exactly as a provider refusal and a non-measurement already are,
        and for the same reason: an attempt is evidence about a route only where the
        route is what varied. A shortfall says a completed run's work did not satisfy a
        contract TEMM wrote and TEMM measures, which is a statement about that contract
        as much as about the route - and defect #63 proved acceptance itself can be the
        reason a delivered screen was called absent.

        Defect #80: a timeout that was delivering work when the clock ran out is left
        out on that same principle, because TEMM picks the clock. The ceiling is a
        dispatch parameter - the caller's guess at how long the task should need - so a
        run stopped at it says the guess was short, or the task was large, and the two
        are indistinguishable from the route's side. What makes it the route's answer is
        producing nothing: a run that reached the ceiling having written no file is
        undelivered however generous the allowance, and still counts here.

        The contradiction this resolves was internal. The very receipts counted against
        the route also *renew* its capability floor: they are classified
        `model_executed` with `model_produced_work`, on the strength of tool calls,
        text, token usage and a workspace diff. Production evidence 2026-08-22 08:13:45.
        `opencode/x-preview-f-free` held five such runs on project-23a514f0c426 - at
        ceilings of 600s, 900s, 1500s, 3000s and 3602s, four of them changing 1, 1, 2
        and 8 files - and attempt-30f37bfabca5, the newest, had renewed all three floor
        capabilities 72 minutes earlier. `lapsed` held exactly three routes;
        `renewal_order` ranked x-preview-f-free first on reachability and
        `openai/gpt-5.4` last, its newest provider interaction a 429 and its floor
        proven 30 hours before. This gate then excluded both `opencode` routes as
        chronic, which made the one route ordering had ranked last into `renewable[0]`.
        The dispatch spent its single probe re-confirming that 429 in 79s, measured
        nothing, wrote no evidence, eliminated nothing, and raised
        `execution_unavailable` with the certified route one renewal away - and would
        have done so again on every dispatch, because the exclusion is recomputed from
        the same unchanging history each time.

        The distinction discriminates rather than forgiving. Re-scored across every
        route on that project, exactly one verdict changes: x-preview-f-free, whose
        undelivered count falls from five to the one timeout that produced no diff.
        `opencode/deepseek-v4-flash-free` stays chronic on 23 undelivered runs, five of
        them timeouts that changed nothing and none cut short, and `opencode/big-pickle`
        stays chronic on six.

        Production evidence 2026-08-22 00:23:59. `opencode/x-preview-f-free` - the
        fleet's one certified route, fifty minutes past an execution of 72 tool uses,
        3.59M tokens and eight changed files, holding a coding floor live for another
        nine - sorted first for renewal on reachability and was then excluded here as
        chronic on seven failures: six acceptance shortfalls, every one classified
        `model_executed` and satisfying one or two of three clauses, and one timeout.
        The probe went instead to `openai/gpt-5.4-fast`, which escaped this gate only by
        holding four of the identical shortfalls rather than five, and whose newest
        provider interaction was a 429. It re-confirmed the 429 in 77 seconds, measured
        nothing, and the dispatch ended in `execution_unavailable` with the certified
        route one renewal away. Both routes had failed the same criterion ids -
        `shell:navigation`, `shell:surface`, `customers:screen`, `customers:search`,
        `rbac:destructive-guards` - which is what a hard contract looks like from every
        route, not what one bad route looks like. Counting shortfalls here made chronic
        status a function of how much work a route had been given, so the routes the
        fleet leans on were the first it disqualified.

        Ranking is untouched and still counts every shortfall, so the route that
        satisfies more of a contract is still preferred. What changes is only that a
        shortfall can no longer withdraw a proven route in favour of an untried one.

        This is deliberately not a blacklist: it gates *preference* between a renewable
        route and an unmeasured one, the caller still renews a chronic route when no
        unmeasured route exists, and because it reads current health every dispatch a
        route that resumes delivering stops being chronic with nothing reset by hand.
        """
        accepted = observed["accepted_writes"]
        undelivered = max(observed["failed"] - observed.get("unmet_contract", 0) - observed.get("cut_short", 0), 0)
        total = accepted + undelivered
        if total == 0 or undelivered < CHRONIC_FAILURE_MIN_FAILURES:
            return False
        return accepted / total < CHRONIC_FAILURE_MAX_ACCEPTANCE_RATE

    @staticmethod
    def _exploration_record(yielded: tuple[datetime, str], health: dict, considered: list[dict]) -> dict:
        """Why exploration was triggered and which production evidence caused it.

        Returned in `route_refresh` and persisted onto the probed route's capability
        evidence through the tournament, so the causal chain - chronic production
        failure to exploration to newly proven route - survives the dispatch that made
        the decision and is auditable from the route it produced.
        """
        total = health["accepted_writes"] + health["failed"]
        return {
            "reason": "all_renewable_routes_chronically_failing_real_production_tasks",
            "yielded_route": yielded[1],
            "yielded_route_last_proven_at": yielded[0].isoformat(),
            "attempts": total,
            "accepted_file_writes": health["accepted_writes"],
            "failed_or_unaccepted": health["failed"],
            "recent_timeout_or_no_effect": health["timeout_no_effect"],
            "runs_cut_short_by_ceiling": health["cut_short"],
            "acceptance_rate": round(health["accepted_writes"] / total, 4) if total else 0.0,
            "chronic_failure_thresholds": {
                "min_failures": CHRONIC_FAILURE_MIN_FAILURES,
                "max_acceptance_rate": CHRONIC_FAILURE_MAX_ACCEPTANCE_RATE,
            },
            "renewable_routes_considered": considered,
        }

    async def _bootstrap_probe(self, session: AsyncSession, never_measured: list[str], trigger: str, exploration: dict | None) -> dict:
        """Measure one never-measured route, round-robin over providers.

        Shared by the two ways a dispatch reaches bootstrap - no renewable route at
        all, and every renewable route chronically failing - so both spend exactly one
        probe, name the same bounded candidate preview, and differ only in the trigger
        and whether an exploration record accompanies them.
        """
        # The rotation is only a rotation if it carries across dispatches. One probe
        # is spent per dispatch, and the ordering is recomputed from scratch each time,
        # so ordering providers by name meant the alphabetically-first provider with an
        # untried route won every dispatch in a row - the depth-first spend the order
        # exists to prevent. Which provider is due is therefore read from what the
        # fleet has already tried.
        candidates = self._provider_round_robin(never_measured, await self._provider_probe_recency(session))
        return {
            **await self._probe_route(
                session, candidates[0], trigger, "provider_round_robin",
                [{"model_id": item} for item in candidates[:BOOTSTRAP_CONSIDERED_PREVIEW]],
                exploration=exploration,
            ),
            "never_measured_routes": len(candidates),
        }

    async def _queue_already_served(self, session: AsyncSession, routes: list[ModelRecord], requirements: list[set[str]], exhausted: set[tuple[str, str]], now: datetime, refused: set[str] | None = None) -> bool:
        """Can some route serve some queued task as things stand, without a probe?

        Both a spent allowance and lapsed availability are read here, because a route
        selection would discard has not served anything however well certified it is.
        Reading only the certification was not enough: the fleet's one certified route
        being refused for a spent allowance persuaded this check the queue was served
        while selection was discarding that same route as unusable, so nothing
        dispatched and nothing was measured.
        """
        if refused is None:
            refused = await self._recent_refusals(session, now - timedelta(seconds=PROVIDER_REFUSAL_TTL_SECONDS))
        for model in routes:
            provider, _, model_name = model.id.partition("/")
            if self._is_exhausted(exhausted, provider, model_name) or self._is_refused(refused, model.id):
                continue
            if not (model.availability_state == "available" and (model.availability_expires_at or now) > now):
                continue
            for required in requirements:
                certified, _ = await self.capabilities.satisfies(session, model.id, required)
                if certified:
                    return True
        return False

    async def _probe_candidates(self, session: AsyncSession, routes: list[ModelRecord], exhausted: set[tuple[str, str]], now: datetime, refused: set[str] | None = None) -> tuple[list[tuple[datetime, str]], list[str]]:
        """Split the fleet into routes renewal can restore and routes never measured.

        Four facts hold a route out of both, each for as long as it is true. A spent
        allowance: the provider refusing this route for the task refuses the probe
        identically, so probing it buys nothing and costs a run. A refusal on the
        route's newest attempt: that measures the account, not the route, so it is
        never recorded as incapacity and needs its own bound or the same refusing
        route is probed on every dispatch. Negative execution evidence: TEMM ran this
        route against the floor and it failed, which is the bound that turns each
        probe into either a won route or an eliminated one. And a live unavailability
        observation, which is the same bound for the failures that are not the route's
        answer at all.

        That last one exists because the elimination bound above is only sound for
        routes the model actually ran for. A probe that never reached the model -
        provider unresolvable from the executor's configuration, model name unknown to
        the CLI, provider rejecting the client or answering unusably - writes no
        capability evidence by design, since none was measured. Without a second bound
        such a route stays indistinguishable from one never tried, so bootstrap picks
        it again on the next dispatch, and again, spending the fleet's one probe per
        dispatch on a route that cannot be measured while the routes behind it are
        never reached. The bound is the runtime unavailability observation the attempt
        records instead of the false verdict: it names the condition, and it expires
        when the condition might have, so an eliminated-for-now route returns on its
        own rather than by hand.

        Expiry is deliberately not read for that last one, in either direction. A
        lapsed pass is exactly what qualifies a route for renewal, and a lapsed
        failure does not un-run the execution that produced it - a route TEMM measured
        as incapable is not a route TEMM has never measured, whatever the evidence's
        TTL says about trusting the claim for selection. Reading expiry here would
        make elimination temporary and put the whole fleet back in the queue every
        hour.
        """
        evidence = await self._execution_evidence(session)
        if refused is None:
            refused = await self._recent_refusals(session, now - timedelta(seconds=PROVIDER_REFUSAL_TTL_SECONDS))
        lapsed: list[tuple[datetime, str]] = []
        never_measured: list[str] = []
        for model in routes:
            provider, _, model_name = model.id.partition("/")
            if self._is_exhausted(exhausted, provider, model_name) or self._is_refused(refused, model.id):
                continue
            if self._unexecutable_now(model, now):
                continue
            latest = evidence.get(model.id, {})
            if any(not row.supported for row in latest.values()):
                continue
            proven_at = self._floor_proven_at(latest)
            if proven_at:
                lapsed.append((proven_at, model.id))
            else:
                never_measured.append(model.id)
        return lapsed, never_measured

    @staticmethod
    def _unexecutable_now(model: ModelRecord, now: datetime) -> bool:
        """Is this route carrying a live observation that it cannot be run right now?

        Read from the availability observation an attempt records when it measured
        nothing - the honest replacement for the incapacity verdict such an attempt
        used to publish. Only a current observation counts: the whole point of
        recording the condition with a TTL is that it is a statement about now, not a
        retirement.
        """
        return (
            model.availability_state == "unavailable"
            and bool(model.availability_expires_at)
            and model.availability_expires_at > now
        )

    async def _provider_probe_recency(self, session: AsyncSession) -> dict[str, datetime]:
        """When each provider's credentials were last exercised by any attempt.

        Any attempt counts, not only a probe: what one dispatch learns and the next
        should not spend itself re-learning is whether a credential answers, and an
        attempt that failed to launch spent the turn just the same.
        """
        rows = (await session.execute(
            select(RunAttemptRecord.model_id, func.max(RunAttemptRecord.started_at))
            .where(RunAttemptRecord.model_id.is_not(None))
            .group_by(RunAttemptRecord.model_id)
        )).all()
        recency: dict[str, datetime] = {}
        for model_id, started_at in rows:
            provider = str(model_id or "").partition("/")[0]
            if not provider or not started_at:
                continue
            if started_at > recency.get(provider, datetime.min):
                recency[provider] = started_at
        return recency

    @staticmethod
    def _provider_round_robin(model_ids: list[str], last_probed: dict[str, datetime] | None = None) -> list[str]:
        """Order never-measured routes so every provider is tried before any is twice.

        Nothing distinguishes one never-measured route from another on the evidence
        TEMM holds: a discovered OpenCode route carries no coding or quality score,
        and reading a preference out of the model's name would be a guess dressed as
        measurement. What is known is that routes share credentials by provider, so
        consecutive routes from one provider are the likeliest to fail for the same
        reason. Depth-first over the largest provider would spend a hundred probes on
        one revoked key before reaching the next credential; one route per provider
        per round reaches every credential in the fleet within a few dispatches.
        Which provider leads is the one waiting longest - never tried before anything
        tried, then oldest attempt first - because a caller that consumes only the head
        of this list gets its rotation from that and nothing else. Production evidence
        2026-08-21: eleven consecutive NEXA dispatches went to `nvidia`, retiring one
        dead route apiece, while `openai`, `opencode`, `tokenrouter` and `zai` held
        thirty-five untried routes between them and were never reached - `nvidia` sorts
        first, and nothing recorded that it had just had its turn. Within a provider the
        order is the route's identifier, so the sequence is reproducible from the fleet
        alone, and providers waiting equally long are ordered by name for the same
        reason.
        """
        last_probed = last_probed or {}
        by_provider: dict[str, list[str]] = defaultdict(list)
        for model_id in sorted(model_ids):
            by_provider[model_id.partition("/")[0]].append(model_id)
        due_first = sorted(by_provider, key=lambda provider: (last_probed.get(provider) or datetime.min, provider))
        ordered: list[str] = []
        for index in range(max((len(items) for items in by_provider.values()), default=0)):
            for provider in due_first:
                if index < len(by_provider[provider]):
                    ordered.append(by_provider[provider][index])
        return ordered

    async def _probe_route(self, session: AsyncSession, model_id: str, trigger: str, selection_basis: str, considered: list[dict], exploration: dict | None = None) -> dict:
        """Run the one tournament stage that demonstrates the coding floor.

        Shared by renewal and bootstrap so the two cannot drift into measuring the
        floor differently, and so a caller reading `route_refresh` can compare them.
        When an `exploration` record is supplied it is persisted through the tournament
        onto the probed route's evidence, and echoed in the result, so the reason this
        route was measured outlives the dispatch.
        """
        # Imported at call time: the tournament dispatches its stages through this
        # service, so the dependency between the two only closes here.
        from .staged_capability_tournament import StagedCapabilityTournamentService

        try:
            outcome = await StagedCapabilityTournamentService().run_tournament(
                session, model_id,
                timeout_per_stage=REVERIFY_STAGE_TIMEOUT_SECONDS,
                stages=[REVERIFY_STAGE_ID],
                exploration=exploration,
            )
        except Exception as exc:
            # A probe is an attempt to restore selection, not a precondition for it.
            # Selection runs next and reports the authoritative outcome, so a failed
            # probe is recorded and dispatch continues to that honest error rather
            # than surfacing this one in its place. The rollback leaves the session
            # usable for the dispatch that follows.
            await session.rollback()
            return {"model_id": model_id, "trigger": trigger, "considered": considered, "error": str(exc), "restored": False, **({"exploration": exploration} if exploration is not None else {})}
        restored, _ = await self.capabilities.satisfies(session, model_id, REVERIFY_CAPABILITIES)
        return {
            "model_id": model_id,
            "trigger": trigger,
            "selection_basis": selection_basis,
            "considered": considered,
            "tournament_id": outcome.get("tournament_id"),
            "stages": [
                {"stage_id": item.get("stage_id"), "passed": item.get("passed"), "error": item.get("error"), "run_id": item.get("run_id")}
                for item in outcome.get("stages", [])
            ],
            "capabilities_renewed": outcome.get("positive_capabilities", []),
            "restored": restored,
            **({"exploration": exploration} if exploration is not None else {}),
        }

    async def _probe_measured(self, session: AsyncSession, probe: dict) -> bool:
        """Did this probe reach the model, whatever the verdict it came back with?

        A probe is spent to learn something about a route, and the two outcomes the
        one-probe-per-dispatch budget is priced for both qualify: a pass wins the
        route, a measured failure eliminates it. Non-measurement is neither. The
        provider refusing the account, the executor never launching, the CLI not
        resolving the route, a process that produced no execution signal at all -
        each describes the surroundings rather than the route, is deliberately
        recorded as no capability evidence at all, and leaves the route exactly as
        untried as it was before the probe ran.

        Read from the attempt receipts of the stages the probe actually ran, because
        that is where the classification is made and the only place it is durable.
        A probe that raised before any stage started carries no stage and no receipt,
        which is non-measurement of the most local kind. A receipt from before
        measurement was recorded says nothing either way and is counted as it always
        was - as an answer - so an old receipt can never be read as grounds for
        spending a further probe.

        A stage that passed is not looked up at all. Passing is the strongest
        measurement there is - the route ran the floor and delivered it, which is why
        the probe's certification is written - and a pass whose receipt could not be
        found is still a pass. Reading the receipt as the sole authority would let a
        won route be mistaken for an unmeasured one and spend a second probe on the
        strength of its own success.
        """
        if probe.get("restored") or any(item.get("passed") for item in probe.get("stages", [])):
            return True
        run_ids = [item.get("run_id") for item in probe.get("stages", []) if item.get("run_id")]
        if not run_ids:
            return False
        attempts = (await session.execute(
            select(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(run_ids))
        )).scalars().all()
        if not attempts:
            return False
        for attempt in attempts:
            measurement = json.loads(attempt.receipt_json or "{}").get("measurement")
            if measurement is None or measurement.get("measured"):
                return True
        return False

    async def _selection_requirements(self, session: AsyncSession, ready: list[str]) -> list[set[str]]:
        """Return the capability sets queued tasks need selection to satisfy.

        Command tasks run without a model, and a certification candidate is named
        outright and bypasses selection, so neither contributes: renewing on their
        behalf would achieve nothing - and, because the tournament dispatches its
        own stages through this service, would recurse. An empty result means no
        queued task reads route evidence at all.
        """
        requirements: list[set[str]] = []
        for task_id in ready:
            task = await session.get(OrchestrationTaskRecord, task_id)
            if not task or task.task_type == "command":
                continue
            needs = json.loads(task.executor_needs_json or "{}")
            if needs.get("certification_model_id"):
                continue
            required = set(needs.get("capabilities", ["coding"]))
            if required not in requirements:
                requirements.append(required)
        return requirements

    async def _execution_evidence(self, session: AsyncSession, model_id: str | None = None) -> dict[str, dict[str, ModelCapabilityEvidenceRecord]]:
        """The newest execution row per route per coding-floor capability.

        Read for the whole fleet in one query, because the alternative is one query
        per route and a fleet holds hundreds of them: the per-route form was
        affordable while only proven routes were considered, and turned a single
        dispatch into roughly a thousand round trips the moment bootstrap had to
        consider every route.

        Only execution rows count. A capability asserted by a manifest or a discovery
        probe says what a route claims; this says what it did.
        """
        query = select(ModelCapabilityEvidenceRecord).where(
            ModelCapabilityEvidenceRecord.source_type == "execution",
            ModelCapabilityEvidenceRecord.capability.in_(sorted(REVERIFY_CAPABILITIES)),
        )
        if model_id is not None:
            query = query.where(ModelCapabilityEvidenceRecord.model_id == model_id)
        rows = (await session.execute(query.order_by(ModelCapabilityEvidenceRecord.observed_at.desc()))).scalars().all()
        latest: dict[str, dict[str, ModelCapabilityEvidenceRecord]] = defaultdict(dict)
        for row in rows:
            latest[row.model_id].setdefault(row.capability, row)
        return latest

    @staticmethod
    def _floor_proven_at(latest: dict[str, ModelCapabilityEvidenceRecord]) -> Optional[datetime]:
        """When these newest rows prove the whole coding floor, and nothing less.

        Expiry is ignored: a lapsed pass is exactly what qualifies a route for
        renewal. Every floor capability must be present and positive, so an old pass
        cannot outvote the later failure that superseded it, and a route measured on
        part of the floor is not treated as having passed all of it.
        """
        if set(latest) != REVERIFY_CAPABILITIES or not all(row.supported for row in latest.values()):
            return None
        return min(row.observed_at for row in latest.values())

    async def _provider_turned_away(self, session: AsyncSession, model_ids: list[str]) -> set[str]:
        """Routes whose newest attempt never got past the provider.

        Unbounded in time on purpose, which is the whole difference from
        `_recent_refusals`. That window exists so a refusing route is retried rather
        than retired, and it is the right bound on *eligibility*. The question here is
        which of several eligible candidates to spend the one renewal on, and for that
        the age of the refusal is not the point: nothing has reached this provider
        since, however long ago it turned us away.
        """
        if not model_ids:
            return set()
        rows = (await session.execute(
            select(RunAttemptRecord).where(RunAttemptRecord.model_id.in_(model_ids))
            .order_by(RunAttemptRecord.started_at.desc())
        )).scalars().all()
        newest: dict[str, RunAttemptRecord] = {}
        for row in rows:
            newest.setdefault(row.model_id, row)
        return {model_id for model_id, row in newest.items() if self._attempt_provider_non_measurement(row)}

    @staticmethod
    def _attempt_provider_non_measurement(row: RunAttemptRecord) -> bool:
        """Did this attempt fail to reach the model for a reason the provider owns?

        `EXECUTOR_LOCAL_FAILURE` and `NO_EXECUTION_SIGNAL` are deliberately not read.
        The first is this host's own fault, and demoting a route because our machine
        failed while dispatching to it would penalise the route for our condition. The
        second names an attempt that settled nothing in either direction. Neither is
        evidence about what the provider will do with the next request.
        """
        try:
            receipt = json.loads(row.receipt_json or "{}")
        except json.JSONDecodeError:
            return False
        measurement = receipt.get("measurement") if isinstance(receipt, dict) else None
        if not isinstance(measurement, dict) or measurement.get("measured"):
            return False
        return measurement.get("classification") in {PROVIDER_REFUSAL, PROVIDER_UNAVAILABLE}

    async def _recent_refusals(self, session: AsyncSession, since: datetime) -> set[str]:
        """Routes whose most recent attempt was a provider refusal since `since`.

        A probe is bounded by recording the route's incapacity, which withdraws it
        until something re-measures. A refusal must not be recorded that way - it
        measures the account, not the route - so refusals need their own bound, or the
        same refusing route is probed on every dispatch and a working one is never
        reached. An allowance refusal already has one in its quota observation; this
        covers every other kind, a revoked key most of all, without inventing a quota
        claim the provider never made.

        Only the newest attempt counts: a route that has since run is not refusing any
        more, whatever it did an hour ago. Only attempts inside the window are read,
        which loses nothing - any attempt newer than one in the window is itself newer
        than `since`, so the newest attempt in the window is the route's newest attempt
        whenever the window holds one at all, and when it holds none the route has no
        recent attempt to be refusing.

        A refusal the provider attributed to the account itself is held for the
        provider, under a `*` entry, because that is the reach of what it says. A
        rejected key is refused identically by every model behind it, so recording it
        one route at a time makes the fleet buy the same fact once per model:
        production evidence 2026-08-21 has thirteen consecutive dispatches probing
        thirteen different `amazon-bedrock` models, each answered "Authentication
        failed: Please make sure your API Key is valid.", with a hundred more bedrock
        routes still queued behind them and no other provider sampled meanwhile.

        The widening is read from the provider's own newest attempt, not from each
        route's: a provider that has served anything since is not refusing the
        account, whatever one sibling was told before it.
        """
        rows = (await session.execute(
            select(RunAttemptRecord).where(
                RunAttemptRecord.model_id.is_not(None),
                or_(RunAttemptRecord.started_at >= since, RunAttemptRecord.completed_at >= since),
            ).order_by(RunAttemptRecord.started_at.desc())
        )).scalars().all()
        newest: dict[str, RunAttemptRecord] = {}
        newest_by_provider: dict[str, RunAttemptRecord] = {}
        for row in rows:
            newest.setdefault(row.model_id, row)
            newest_by_provider.setdefault(row.model_id.partition("/")[0], row)
        holds = {model_id for model_id, row in newest.items() if self._attempt_refusal(row)}
        for provider, row in newest_by_provider.items():
            refusal = self._attempt_refusal(row)
            if provider and refusal and refusal.get("refusal_scope") == "provider":
                holds.add(f"{provider}/*")
        return holds

    @staticmethod
    def _attempt_refusal(row: RunAttemptRecord) -> Optional[dict]:
        """The provider refusal an attempt recorded, if it recorded one."""
        try:
            receipt = json.loads(row.receipt_json or "{}")
        except json.JSONDecodeError:
            return None
        refusal = receipt.get("provider_refusal") if isinstance(receipt, dict) else None
        return refusal if isinstance(refusal, dict) else None

    @staticmethod
    def _is_refused(refused: set[str], model_id: str) -> bool:
        """Is this route held out by a refusal - its own, or its whole provider's?

        `*` mirrors the quota ledger's convention for the same distinction, and for
        the same reason: what a provider says about the account it says about every
        model behind it, so one attempt is the whole cost of learning it.
        """
        return model_id in refused or f"{model_id.partition('/')[0]}/*" in refused

    async def _last_proven_by_execution(self, session: AsyncSession, model_id: str) -> Optional[datetime]:
        """When this one route last proved the whole coding floor by execution."""
        evidence = await self._execution_evidence(session, model_id)
        return self._floor_proven_at(evidence.get(model_id, {}))

    def _effective_timeout(self, task_type: str, timeout_seconds: float | None) -> float:
        """Resolve the execution bound for a task.

        The per-type policy is the default for callers that do not state a bound. An
        explicit caller bound is authoritative in both directions: the policy used to
        be applied with `min()`, which made it an unraisable ceiling, so a route that
        needed longer than the default could never finish an implementation task.
        """
        if timeout_seconds is not None:
            return timeout_seconds
        return TIMEOUT_POLICIES.get(task_type, DEFAULT_TIMEOUT_SECONDS)

    async def _live_active_ids(self, session: AsyncSession, candidates: list[str]) -> list[str]:
        """Keep only task IDs whose persisted state is genuinely still in flight."""
        live: list[str] = []
        for task_id in dict.fromkeys(candidates):
            task = await session.get(OrchestrationTaskRecord, task_id)
            if task and task.state in IN_FLIGHT_DISPATCH_STATES:
                live.append(task_id)
        return live

    async def _recover_orphaned_tasks(self, session: AsyncSession, project_id: str) -> None:
        """Return a task whose run ended without it to the queue.

        Dispatch admits only `planned` tasks and nothing else reclaims one, so a task
        left in `ready` or `running` behind a terminal run is stranded for good: the
        queue can never retry it and its requirement can never complete. Both states
        occur for real, and only the first was recovered:

        - `ready` + terminal run is a run that died before, or during, its attempt.
        - `running` + terminal run is a run finalized by something other than the
          dispatch that owns the task - a restart marking it `interrupted`, or a
          cancellation. `_dispatch_ai` finalizes the run before it transitions the
          task, so the conflicting finalization aborts the dispatch one step short of
          the transition and leaves the task behind. run-bb95c7c6a4c7 stranded
          task-8b69c00490e3 this way, with its own attempt recording every acceptance
          criterion satisfied.

        Recovery is always to `planned` and never to `completed`, however good the
        attempt's record looks: `transition` requires a completed run to complete a
        task, and the run on record is terminal in another state. Claiming completion
        against it would assert something the records contradict. The following pass's
        `retire_unprovable_queue` is the honest route for a contract the workspace now
        satisfies - it retires the task and raises a finding instead of inventing a run.

        A still-live attempt is the one case to leave alone. A run's status can run
        ahead of its executor - that is precisely what restart recovery does - and
        reclaiming a task while its process is still writing would send a second
        executor into the same workspace.
        """
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(
            OrchestrationTaskRecord.project_id == project_id,
            OrchestrationTaskRecord.state.in_(["ready", "running"]),
            OrchestrationTaskRecord.current_run_id.is_not(None),
        ))).scalars().all()
        task_service = __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService()
        for task in tasks:
            run = await session.get(TaskRun, task.current_run_id)
            if not run or run.status not in {"failed", "timed_out", "cancelled", "interrupted"}:
                continue
            live_attempt = (await session.execute(select(RunAttemptRecord.id).where(
                RunAttemptRecord.run_id == task.current_run_id,
                RunAttemptRecord.status.in_(["starting", "running"]),
            ))).scalars().first()
            if live_attempt:
                continue
            await task_service.transition(session, task.id, "blocked")
            await task_service.transition(session, task.id, "planned")

    # ... rest of the class remains unchanged ...
    
    async def cancel(self, session: AsyncSession, checkpoint_id: str) -> dict:
        checkpoint = await session.get(OrchestrationCheckpointRecord, checkpoint_id)
        if not checkpoint:
            raise DomainError("resource_not_found", message="Orchestration checkpoint was not found.")
        tasks = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == checkpoint.project_id, OrchestrationTaskRecord.current_run_id.is_not(None)))).scalars().all()
        cancelled = []
        for task in tasks:
            run = await session.get(TaskRun, task.current_run_id)
            if not run or run.status not in {"created", "running", "cancellation_requested"}:
                continue
            if run.status != "cancellation_requested":
                await self.runs.request_cancel(session, run.id)
            attempt = await session.get(RunAttemptRecord, run.current_attempt_id) if run.current_attempt_id else None
            process_id = f"orchestration-{task.id}-{attempt.id}" if attempt else None
            stopped = await self.manager.cancel(process_id) if process_id else False
            if task.state in {"planned", "ready", "running", "blocked", "failed"}:
                task.state = "cancelled"
                task.revision += 1
                await session.commit()
            cancelled.append({"task_id": task.id, "run_id": run.id, "process_id": process_id, "process_cancelled": stopped})
        checkpoint = await self.recovery.save(session, checkpoint.project_id, "cancelled", {**json.loads(checkpoint.cursor_json or "{}"), "cancelled": True}, [], [], [], checkpoint.id, checkpoint.revision)
        return {"checkpoint": checkpoint.to_dict(), "cancelled_executions": cancelled}

    async def _exhausted_routes(self, session: AsyncSession, now: datetime) -> set[tuple[str, str]]:
        """Routes a provider is currently refusing because their allowance is spent.

        Shared by selection and by renewal so the two cannot disagree about which
        routes can serve work. Selection alone was not enough: renewal stands down
        the moment it finds one available certified route, so an exhausted route
        whose capability evidence had not yet lapsed persuaded renewal that the
        queue was already served, while selection was discarding that same route as
        unusable. Nothing dispatched and nothing renewed, and the fleet sat idle
        with four healthy proven routes one probe away.
        """
        rows = (await session.execute(
            select(QuotaObservationRecord).where(QuotaObservationRecord.expires_at > now)
        )).scalars().all()
        return {(row.provider_instance_id, row.scope) for row in rows if row.remaining_value == 0}

    @staticmethod
    def _is_exhausted(exhausted: set[tuple[str, str]], provider: str, model: str) -> bool:
        """A `*` scope is the provider refusing everything; a named scope, one model."""
        return (f"opencode:{provider}", model) in exhausted or (f"opencode:{provider}", "*") in exhausted

    async def _route_health(self, session: AsyncSession, project_id: str) -> dict:
        """Measure every route by what it did on this project's own work.

        Shared by selection and by renewal so the two cannot disagree about which
        route is performing: renewal used to pick purely by how recently a route was
        proven, which is a measure of the last renewal rather than of the route.

        An attempt the provider refused is left out of the measurement entirely. It
        records the state of an account, not the behaviour of a route, and the two
        come apart the moment the allowance returns - so counting it would leave a
        recovered route carrying penalties for requests it was never given. The
        refusal is not thereby ignored: `is_exhausted` holds the route out of
        selection and out of the tournament for as long as the observation stands,
        which is the mechanism that matches how long the fact is true for.

        A refusal is one way an attempt can measure nothing, and every other way needs
        leaving out for the same reason. An attempt is a statement about a route only
        if the route ran: a local executor that never launched, a provider that was
        unreachable, and a process that produced no execution signal at all each
        describe the host or the account, and counting them makes a route look worse
        the worse its surroundings behave. The consequence is not confined to ranking,
        because `_chronic_production_failure` reads these same counts to decide whether
        a route may be renewed at all. Production evidence 2026-08-21:
        attempt-0144bc5d1502 aborted in the CLI's own runtime on `MemoryExhaustion`
        31s in, exit 0xC0000409, before one model step - no events, no tokens, no diff -
        and it was `opencode/x-preview-f-free`'s fifth recorded failure on this project,
        which is exactly `CHRONIC_FAILURE_MIN_FAILURES`. So a memory condition on this
        machine turned the fleet's one certified route chronic, the dispatch yielded its
        only probe to an unmeasured route, and a queue with a working route sat behind
        `execution_unavailable`.

        `cut_short` is the same distinction one step further in, for attempts that did
        reach the model: a timeout that was producing work when the clock ran out. It is
        recorded here rather than derived by the reader because only the receipt knows
        whether a run had an effect, and only `_chronic_production_failure` may act on
        it - ranking reads the raw counters and is unchanged.

        Non-measurement holds its route out through
        `NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS` for as long as the condition is
        known to hold, which - exactly as with the refusal - is the mechanism that
        matches how long the fact is true for.

        Only a receipt that carries a measurement is read this way. An attempt from
        before measurement was recorded says nothing either way, and is counted as it
        always was rather than silently dropped out of the history.
        """
        attempt_rows = (await session.execute(
            select(RunAttemptRecord, TaskRun, OrchestrationTaskRecord.state)
            .join(TaskRun, TaskRun.id == RunAttemptRecord.run_id)
            .outerjoin(OrchestrationTaskRecord, OrchestrationTaskRecord.current_run_id == TaskRun.id)
            .where(TaskRun.project_id == project_id, RunAttemptRecord.model_id.is_not(None))
        )).all()
        history = defaultdict(lambda: {"accepted_writes": 0, "failed": 0, "recent_failures": 0, "timeout_no_effect": 0, "unmet_contract": 0, "cut_short": 0, "duration_ms": 0})
        for attempt, run, task_state in attempt_rows:
            receipt = json.loads(attempt.receipt_json or "{}")
            measurement = receipt.get("measurement")
            if receipt.get("provider_refusal") or measurement and not measurement.get("measured"):
                # Touch the entry so a route known only by non-measurement still
                # appears in the ranking, at the neutral score an untried route
                # carries - which is what it is: still untried.
                history[attempt.model_id]
                continue
            item = history[attempt.model_id]
            if attempt.status == "completed" and run.status == "completed" and task_state == "completed":
                item["accepted_writes"] += 1
            else:
                item["failed"] += 1
            if attempt.status in {"failed", "timed_out"}:
                item["recent_failures"] += 1
                if attempt.status == "timed_out" or receipt.get("no_effect") or receipt.get("completion_detection", {}).get("reason") == "no_effect":
                    item["timeout_no_effect"] += 1
            # Counted alongside the failure rather than instead of it. Ranking should
            # keep preferring the route that satisfies more of a contract, so `failed`
            # and `recent_failures` are left exactly as they were; the one reader that
            # *excludes* a route needs to tell a shortfall apart from a run the route
            # never delivered, and this is where that distinction is available. Only a
            # receipt that says the model executed can name a shortfall: an attempt from
            # before measurement was recorded is counted as it always was.
            if attempt.error_code == "acceptance_unsatisfied" and (measurement or {}).get("classification") == MODEL_EXECUTED:
                item["unmet_contract"] += 1
            # The second such distinction, counted the same way and read by the same
            # single reader. A run TEMM stopped at its own ceiling while the route was
            # delivering work is a fact about the ceiling and the size of the task; what
            # makes a timeout the route's own answer is reaching the ceiling having
            # written nothing, so the effect is what is tested here and `no_effect` is
            # not enough on its own - attempt-df279e00dbda timed out with an empty diff
            # and `no_effect: false`. Only a receipt that says the model executed can
            # name a run cut short, for the same reason it governs the line above.
            #
            # Defect #81: a non-empty diff was the whole test, so any change at all
            # excused the timeout - including a run that did none of the work it was
            # directed at. attempt-d2389464cdd4 was told to delete four debris files,
            # deleted none, changed seven files its focus never named, and was credited
            # as a route delivering work when TEMM stopped it. `focus_adherence` already
            # measures exactly that question, so the excuse is conditioned on it: a
            # `touched_none` verdict means the diff is not progress on the directed work
            # and cannot stand in for it. Since #76 the verdict covers removal-only
            # focus too, so a directive of four deletions with none performed reaches
            # here as `touched_none` rather than as an undirected run. Receipts with no
            # verdict - written before this reading existed, or genuinely undirected -
            # keep the credit they had: the absent measurement is a gap in TEMM's own
            # evidence and must not be charged to the route as non-delivery.
            focus_verdict = (receipt.get("focus_adherence") or {}).get("verdict")
            if attempt.status == "timed_out" and bool(receipt.get("workspace_diff")) and (measurement or {}).get("classification") == MODEL_EXECUTED and focus_verdict != "touched_none":
                item["cut_short"] += 1
            item["duration_ms"] += int(receipt.get("duration_ms") or 0)
        return history

    async def _select_model(self, session: AsyncSession, task: OrchestrationTaskRecord, agent: AgentRecord | None = None) -> dict:
        """Select an executable model using complexity and measured project history."""
        needs = json.loads(task.executor_needs_json or "{}")
        required_capabilities = set(needs.get("capabilities", ["coding"]))
        if task.task_type == "command":
            return {"provider": None, "model": None, "reason": "Command task does not require AI model"}
        if agent and agent.id != "opencode-cli" and needs.get("agent_id") == agent.id:
            return {
                "provider": agent.id,
                "model": None,
                "model_id": None,
                "tier": "agent",
                "protocol": agent.adapter_id or agent.id,
                "reason": "Explicitly assigned verified executor agent",
                "availability": "verified",
                "required_capabilities": sorted(required_capabilities),
                "selection_basis": "explicit_executor_agent",
                "candidate_routes": [],
                "capability_rejections": [],
            }
        certification_model = needs.get("certification_model_id")
        if certification_model:
            model = await session.get(ModelRecord, certification_model)
            if not model or model.source_type != "external_tool" or model.source_uri != "opencode-cli" or model.lifecycle_status != "active" or not model.is_active:
                raise DomainError("execution_unavailable", message="Certification candidate is not an active OpenCode route.")
            provider, model_name = certification_model.split("/", 1)
            return {"provider": provider, "model": model_name, "model_id": certification_model, "tier": "balanced", "protocol": "opencode", "reason": "Production-contract certification candidate", "availability": "certification", "required_capabilities": sorted(required_capabilities), "selection_basis": "certification_candidate", "candidate_routes": [{"provider": provider, "model": model_name, "model_id": certification_model, "availability": "certification"}], "capability_rejections": []}

        words = len(f"{task.title} {task.description}".split())
        preferred_tier = "fast" if words <= 180 else "balanced" if words <= 450 else "strong"
        history = await self._route_health(session, task.project_id)

        now = datetime.utcnow()
        discovered = (await session.execute(
            select(ModelRecord).where(
                ModelRecord.source_type == "external_tool",
                ModelRecord.source_uri == "opencode-cli",
                ModelRecord.lifecycle_status == "active",
                ModelRecord.is_active.is_(True),
                ModelRecord.availability_state == "available",
                ModelRecord.availability_expires_at > now,
            )
        )).scalars().all()
        candidates = []
        rejected_capabilities = []
        for model in discovered:
            certified, capability_evidence = await self.capabilities.satisfies(session, model.id, required_capabilities)
            item = {
                "provider": model.provider,
                "model": model.id.split("/", 1)[1] if "/" in model.id else model.id,
                "model_id": model.id,
                "tier": model.category if model.category in {"fast", "balanced", "strong"} else "strong" if model.category in {"coding", "reasoning"} else "balanced",
                "protocol": "opencode",
                "reason": "Verified by current OpenCode execution evidence",
                "availability": "verified",
                "capability_evidence": capability_evidence,
            }
            if certified:
                candidates.append(item)
            else:
                rejected_capabilities.append({"model_id": model.id, "missing_capabilities": capability_evidence["missing"]})
        rejected_capabilities.extend({"model_id": f"{item['provider']}/{item['model']}", "missing_capabilities": sorted(required_capabilities), "reason": "legacy_route_has_no_current_capability_evidence"} for item in CODING_MODELS if not any(candidate["provider"] == item["provider"] and candidate["model"] == item["model"] for candidate in candidates))

        exhausted = await self._exhausted_routes(session, now)
        # A refusal is bounded here for the same reason it is in the probe path: it is
        # never recorded as the route's incapacity, so without its own bound selection
        # ranks a refusing route exactly as it did before the refusal and picks it
        # again on every dispatch. The quota ledger covers a spent allowance; a
        # rejected key makes no quota claim and would otherwise be unbounded.
        refused = await self._recent_refusals(session, now - timedelta(seconds=PROVIDER_REFUSAL_TTL_SECONDS))

        def is_unusable(candidate: dict) -> bool:
            return self._is_exhausted(exhausted, candidate["provider"], candidate["model"]) or self._is_refused(refused, candidate["model_id"])

        def rank(candidate: dict) -> tuple:
            observed = history[candidate["model_id"]]
            total = observed["accepted_writes"] + observed["failed"]
            success_rate = observed["accepted_writes"] / total if total else None
            average_ms = observed["duration_ms"] / total if total else None
            tier_penalty = 0 if candidate["tier"] == preferred_tier else 1
            availability_penalty = 0 if candidate.get("availability") == "verified" else 1
            # A route with < 50% success rate is worse than an untried route;
            # untried routes get a neutral penalty of 0, poor routes get 1.
            history_penalty = 1 if success_rate is not None and success_rate < 0.5 else 0
            recent_failure_penalty = min(observed["recent_failures"], 3)
            timeout_no_effect_penalty = min(observed["timeout_no_effect"], 3)
            return (is_unusable(candidate), availability_penalty, timeout_no_effect_penalty, recent_failure_penalty, history_penalty, tier_penalty, average_ms or float("inf"))

        ranked = sorted(candidates, key=rank)
        executable = [item for item in ranked if not is_unusable(item)]
        if not executable:
            # A locally installed CLI is itself an executable route, OpenCode included:
            # `_build_argv_with_model` hands a model only to an OpenCode route that has
            # one, and invokes every agent without a model through its own declared
            # invocation. So when no model route has current capability evidence,
            # refusing the dispatch discarded the one route that could actually run -
            # and the readiness gate had just handed the owner exactly that route, so
            # the gate promised what the dispatcher then refused. Production evidence
            # for the v0.1.1 hotfix: an OpenCode-only machine (discovery verified, auth
            # checked) could never dispatch a project task, because this fallback
            # excluded `opencode-cli` by id and per-model capability evidence did not
            # exist until routes were individually probed. Preferred second, never
            # first: a route with execution-proven capability evidence still wins,
            # which keeps the model ledger, census and renewal on the routes they
            # belong to. The agent is accepted on the same evidence the gate used -
            # `AgentAssignmentService` has already required it to be verified,
            # authenticated, permitted for this workspace, and to declare every
            # capability the task asked for.
            if agent:
                return {
                    "provider": agent.id,
                    "model": None,
                    "model_id": None,
                    "tier": "agent",
                    "protocol": agent.adapter_id or agent.id,
                    "reason": "Verified executor agent satisfies the task capability contract",
                    "availability": "verified",
                    "required_capabilities": sorted(required_capabilities),
                    "selection_basis": "verified_capability_agent",
                    "candidate_routes": [],
                    "capability_rejections": rejected_capabilities,
                    "unavailable_model_routes": [item["model_id"] for item in ranked],
                }
            # The bare code said a queue was stuck without saying what stopped it, so
            # every diagnosis of `execution_unavailable` meant reading the ranking back
            # out of the database by hand. The three reasons a candidate is dropped are
            # already computed here; they now travel with the error.
            raise DomainError(
                "execution_unavailable",
                message="No coding route has current executable availability.",
                details={
                    "required_capabilities": sorted(required_capabilities),
                    "discovered_routes": len(discovered),
                    "candidates": [item["model_id"] for item in ranked],
                    "rejected_capabilities": rejected_capabilities,
                    "exhausted": [item["model_id"] for item in ranked if self._is_exhausted(exhausted, item["provider"], item["model"])],
                    "refused": [item["model_id"] for item in ranked if self._is_refused(refused, item["model_id"])],
                    "host": host_observation(),
                },
            )
        candidate = executable[0]
        observed = history[candidate["model_id"]]
        return {
            **candidate,
            "required_capabilities": sorted(required_capabilities),
            "selection_basis": "task_complexity_and_project_attempt_history",
            "task_word_count": words,
            "preferred_tier": preferred_tier,
            "observed_attempts": observed["accepted_writes"] + observed["failed"],
            "candidate_routes": [
                {
                    **item,
                    "observed_attempts": history[item["model_id"]]["accepted_writes"] + history[item["model_id"]]["failed"],
                    "accepted_file_writes": history[item["model_id"]]["accepted_writes"],
                    "failed_or_unaccepted": history[item["model_id"]]["failed"],
                    "recent_failures": history[item["model_id"]]["recent_failures"],
                    "recent_timeout_or_no_effect": history[item["model_id"]]["timeout_no_effect"],
                    "temporarily_unavailable": is_unusable(item),
                }
                for item in ranked
            ],
            "capability_rejections": rejected_capabilities,
        }

    async def _context_budget(self, session: AsyncSession, route_decision: dict, prompt: str, stated_limit: int | None) -> dict:
        """How many tokens the context pack may spend, and on whose authority.

        A caller that states a ceiling gets exactly that ceiling and no reserve: the
        capability tournament keeps its probe packs deliberately small, and that is a
        decision about the probe rather than an estimate of a window.

        With nothing stated the budget is the selected route's own declared window,
        less the prompt and a reply allowance - because a fixed default is a number
        about no route in particular. Production evidence 2026-08-20: every repair
        dispatch of `checkpoint-a8d3277ebe57` failed `resource_conflict` against a
        32000-token default while the route in hand declared 128000, so the fleet
        vetoed on pack-provenance grounds the exact work reconciliation had just
        found outstanding.
        """
        prompt_tokens = max(1, len(prompt) // PROMPT_TOKEN_DIVISOR)
        if stated_limit is not None:
            return {"basis": "caller_declared_ceiling", "token_limit": stated_limit, "reserved_tokens": 0, "prompt_tokens": prompt_tokens, "route_context_window": None}
        model = await session.get(ModelRecord, route_decision["model_id"]) if route_decision.get("model_id") else None
        window = model.context_window if model and model.context_window and model.context_window > 0 else None
        limit = window or DEFAULT_CONTEXT_PACK_TOKENS
        reserved = min(prompt_tokens + CONTEXT_REPLY_RESERVE_TOKENS, max(limit - MIN_CONTEXT_PACK_TOKENS, 0))
        return {"basis": "route_context_window" if window else "no_declared_route_window", "token_limit": limit, "reserved_tokens": reserved, "prompt_tokens": prompt_tokens, "route_context_window": window}

    async def _hold_non_measured_route(self, session: AsyncSession, model_id: Optional[str], measurement: dict, *, run_id: str, attempt_id: str, provider_propagation: dict, host: dict | None = None) -> dict:
        """Withhold a route that measured nothing, and report whether the hold took.

        The hold used to be written and forgotten: a route TEMM holds no model record
        for raised `resource_not_found`, which was swallowed silently, so a hold that
        could not be written was indistinguishable from one that was. That silence hid
        defect #37 for eleven dispatches - the phantom route could not be held, so it
        was re-probed every time, and nothing said so. What the hold did, or could not
        do, now travels on the attempt's receipt beside the classification it follows
        from.

        An attempt that never reached the model measured nothing about it. A
        launch failure is the executor's, not the route's: the process was never
        started, so no capability was exercised and none may be recorded. It was
        written as `{capability: False}` here, which is the same defect as the
        tournament's - production evidence 2026-08-20, run-133922d95108, has a
        route recorded as unable to code by an attempt whose provider the
        executor never resolved. What such an attempt does establish is that the
        route is not executable right now, so that is what is recorded, on a
        bounded TTL and without touching the capability evidence a real earlier
        execution proved. Selection already requires a current availability
        observation, so the dead route stops being chosen either way - and it has
        to, or the next task selects it again and buys the same non-measurement.
        This covers the failure at the provider as well as the one below it:
        `run-1a23ad2eff63` reached its provider with the propagated configuration
        and got a null body back, which is no more a measurement of the route than
        not finding the provider was, and no less a reason to stop dispatching to
        it until the condition clears.
        """
        # How long, and on whose authority - the provider's word on whether its answer
        # is an outage or a retirement, falling back to the classification's own TTL.
        hold = non_measurement_hold(measurement, host)
        ttl_seconds = hold["ttl_seconds"]
        outcome = {"held": False, "classification": measurement["classification"], "model_id": model_id, **hold}
        if measurement["measured"]:
            return {**outcome, "reason": "route_was_measured"}
        if hold.get("attribution") == "host":
            # The machine failed, not the route, and the route was never asked. Holding
            # it would record nothing true and would move dispatch onto a route that
            # dies the same way. The host reading travels on the receipt so the decision
            # is auditable rather than a silent omission.
            return {**outcome, "reason": "host_condition_not_charged_to_route"}
        if not ttl_seconds:
            return {**outcome, "reason": "classification_carries_no_hold"}
        if not model_id:
            return {**outcome, "reason": "route_has_no_identity"}
        try:
            await model_registry_service.record_observation(
                session,
                model_id,
                state="unavailable",
                source="runtime",
                evidence={
                    "reason": measurement["reason"],
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "classification": measurement["classification"],
                    "permanence": hold["permanence"],
                    "permanence_basis": hold["permanence_basis"],
                    "error_events": measurement["error_events"],
                    "provider_propagation": provider_propagation,
                    "production": True,
                },
                ttl_seconds=ttl_seconds,
            )
        except DomainError as exc:
            # A route TEMM does not hold a model record for cannot carry an
            # observation. That is now said out loud rather than passed over: an
            # unholdable route is re-probed on the next dispatch, and the receipt is
            # where that fact is available to whoever asks why.
            return {**outcome, "reason": "no_model_record_for_route", "error_code": exc.code}
        return {**outcome, "held": True, "reason": measurement["reason"]}

    async def _renew_measured_route(self, session: AsyncSession, model_id: Optional[str], measurement: dict, *, run_id: str, attempt_id: str, provider_propagation: dict) -> dict:
        """Refresh executable availability from the attempt that just ran the route.

        Executable availability was granted in exactly one place - the staged
        tournament promoting a route that passed the certification floor - and it
        expires. So a route TEMM had just run for real went unavailable half an hour
        later and had to be re-bought with another probe run, while the receipt of the
        work sat in the same database. Production evidence 2026-08-21: `openai/gpt-5.4`
        was certified at 01:11:33 by tournament `47e141465271`, dispatched immediately
        onto NEXA as `run-6da28fdf1757` - 347 seconds, 2.08M tokens, real file writes -
        and its availability lapsed at 01:41:33. At 02:00:32 the next dispatch found no
        available route, spent its one probe exploring `aliyun/qwen3-max-2025-09-23`,
        which the provider refused for a spent allowance, and raised
        `execution_unavailable` about a fleet whose newest execution evidence was a
        route that had worked for nearly six minutes.

        A finalized attempt classified `model_executed` is the stronger observation of
        the two: the certification floor is a single trivial file write, while this is
        the same executor, the same credentials and the same route doing the project's
        actual work, measured later. It is read for availability alone - whether TEMM
        can execute this route right now - and never for capability. Capability is a
        claim about what the route can do, which only a controlled contract measures,
        and an attempt that ran and missed acceptance says nothing about that (defects
        #9 and #11); this method never writes capability evidence in either direction,
        so the elimination bound behind `_probe_candidates` is untouched.

        This is the positive direction of `_hold_non_measured_route` and takes its
        classification from the same place, so the two can never both fire: a
        non-measurement grants nothing here, which is the whole of principle 2 at this
        seam. An executor that never resolved the provider, a provider that refused the
        key or the allowance, a run stopped before the model answered - each leaves
        availability exactly as it was for the hold to speak about, because none of
        them observed the route being executable.
        """
        ttl_seconds = executable_availability_ttl_seconds()
        outcome = {"renewed": False, "classification": measurement["classification"], "model_id": model_id, "ttl_seconds": ttl_seconds}
        if not measurement["measured"]:
            # The route was not observed executing, so nothing here has anything to say
            # about it. `_hold_non_measured_route` is where this attempt is read.
            return {**outcome, "reason": "route_was_not_measured"}
        if not model_id:
            return {**outcome, "reason": "route_has_no_identity"}
        now = datetime.utcnow()
        record = await session.get(ModelRecord, model_id)
        if record and record.availability_state == "available" and record.availability_expires_at and record.availability_expires_at >= now + timedelta(seconds=ttl_seconds):
            # A longer-lived observation already covers this window. Overwriting it
            # would shorten the fleet's knowledge of the route on the strength of
            # having proven it again, which is backwards.
            return {**outcome, "reason": "current_observation_outlasts_this_one", "availability_expires_at": record.availability_expires_at.isoformat()}
        try:
            renewed = await model_registry_service.record_observation(
                session,
                model_id,
                state="available",
                source="runtime",
                evidence={
                    "reason": measurement["reason"],
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "classification": measurement["classification"],
                    "execution_proof": measurement.get("execution_proof", []),
                    "tokens_reported": measurement.get("tokens_reported"),
                    "provider_propagation": provider_propagation,
                    "capability_scope": "availability_only",
                    "production": True,
                },
                ttl_seconds=ttl_seconds,
            )
        except DomainError as exc:
            # Said out loud for the same reason the hold says it: a route TEMM holds no
            # model record for cannot carry an observation, and the receipt is where
            # that fact is available to whoever asks why the route lapsed anyway.
            return {**outcome, "reason": "no_model_record_for_route", "error_code": exc.code}
        return {**outcome, "renewed": True, "reason": measurement["reason"], "execution_proof": measurement.get("execution_proof", []), "availability_expires_at": renewed.availability_expires_at.isoformat()}

    async def _renew_measured_capabilities(self, session: AsyncSession, model_id: Optional[str], measurement: dict, *, run_id: str, attempt_id: str, workspace_diff: list[dict]) -> dict:
        """Renew the capability floor from what this attempt demonstrably did on disk.

        Selection gates on two things: executable availability, and current evidence
        that the route satisfies the coding floor. `_renew_measured_route` renews the
        first from the production attempt that ran the route and deliberately leaves
        the second alone, because a capability claim may not be inferred from an
        attempt's disappointment (defects #9, #11, #29). That reasoning is about
        *negative* claims. Held for positive ones too, it left the floor to expire an
        hour after the last controlled probe while real work was flowing, and a route
        TEMM had just run for six minutes was discarded as uncertified.

        Production evidence 2026-08-21: `openai/gpt-5.4` was certified at 02:26:14 and
        lapsed at 03:26:14 mid-attempt. `attempt-9f20aee6a59d` ran 13 steps and 38 tool
        calls and left `frontend/src/pages/ActivityPage.tsx` modified, which renewed its
        availability to 03:56:56. The dispatch four seconds later dropped the route for
        want of capability evidence, spent its one renewal probe on the lapsed
        `aliyun/qwen3-max-2025-09-23` - refused for a spent allowance - and raised
        `execution_unavailable` about a fleet whose newest execution evidence was a
        route that had just done the project's work. Five tasks sat behind it.

        What is claimed here is only what the workspace diff proves, and only in the
        positive direction:

          * `file_write` - the executor changed a file in the bound workspace. Every
            change qualifies, a deletion included: removing a file is a write.
          * `coding` - it authored content, so a path was added or modified. This is
            the tournament's own floor standard for the capability, which certifies
            `coding` on a single verified file write in a controlled workspace; this
            is that write, in the project's real tree, against a real requirement.
          * `file_read` - it modified a path that already existed, whose `before` hash
            differs from its `after`. Editing content in place is reading it.

        Nothing else is renewed. Capabilities beyond the floor stay with the probe that
        measures them under a controlled contract, and a proof this receipt does not
        carry is left to lapse: an attempt that only deleted files renews `file_write`
        and nothing more, and the next dispatch measures the rest.

        No negative observation is written in any circumstance - not for an unsatisfied
        contract, not for an empty diff, not for a non-measurement. A route that stops
        producing simply stops renewing, its evidence lapses, and the controlled probe
        takes over, so the elimination bound behind `_probe_candidates` is untouched
        and the loop stays self-healing. Attempt quality remains the business of
        `rank()`, which demotes a weak route by its history without hard-gating it out
        of selection.
        """
        outcome = {"renewed": [], "classification": measurement["classification"], "model_id": model_id}
        if not measurement.get("capability_conclusion_admissible"):
            # The model was not observed executing, so this attempt has nothing to say
            # about the route in either direction.
            return {**outcome, "reason": "route_was_not_measured"}
        if not model_id:
            return {**outcome, "reason": "route_has_no_identity"}
        changes = [entry.get("change") for entry in workspace_diff or [] if isinstance(entry, dict)]
        proven = {
            "file_write": bool(changes),
            "coding": any(change in {"added", "modified"} for change in changes),
            "file_read": any(change == "modified" for change in changes),
        }
        supported = sorted(capability for capability in REVERIFY_CAPABILITIES if proven.get(capability))
        if not supported:
            # The route executed but left no filesystem evidence to read a capability
            # from. Saying nothing is the whole point: an empty diff is not incapacity.
            return {**outcome, "reason": "attempt_produced_no_filesystem_evidence"}
        await self.capabilities.certify(
            session,
            model_id,
            {capability: True for capability in supported},
            {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "probe": "production_workspace_effect",
                "classification": measurement["classification"],
                "reason": measurement["reason"],
                "execution_proof": measurement.get("execution_proof", []),
                "changes_observed": sorted({change for change in changes if change}),
                "production": True,
                "positive_only": True,
            },
        )
        return {**outcome, "renewed": supported, "reason": "production_workspace_effect"}

    async def _record_run_telemetry(self, session: AsyncSession, run_id: str, attempt_id: str | None, *, task_type: str, model_id: str | None = None, agent_id: str | None = None, workspace_id: str | None = None, duration_ms: int | None = None, census: dict | None = None) -> None:
        """Write what a run actually spent onto the run that spent it.

        The orchestration path finalized a run with a status and nothing else: no
        selected model, no tokens, no duration, provenance left at the column
        defaults. Production evidence 2026-08-20 - `run-1a2485f7a408` executed
        `aliyun/qwen3-max` for 641s across 33 steps and 139600 reported tokens, and
        its row carried model `None`, zero tokens and zero milliseconds - so every
        real execution the fleet performed was invisible to `telemetry_export`, which
        reads exactly these fields. Interactive runs recorded all of it; only the runs
        that did the project's work did not.

        Each dimension carries the provenance it earned: the token census is the
        executor's own per-step report, the duration is the process wall clock, and
        cost stays unknown because an OpenCode route has no resolved price - an absent
        price is not a cost of zero.
        """
        run = await session.get(TaskRun, run_id)
        if not run:
            return
        reported = bool(census and census.get("reporting_events"))
        run.task_type = task_type
        if model_id:
            run.selected_model_id = model_id
        if agent_id:
            run.selected_agent_id = agent_id
        if workspace_id:
            run.workspace_id = workspace_id
        if reported:
            run.input_tokens = census["input"]
            run.output_tokens = census["output"]
            run.cached_tokens = census["cache_read"] + census["cache_write"]
        run.token_provenance = "provider_reported" if reported else "unknown"
        if duration_ms is not None:
            run.duration_ms = int(duration_ms)
            run.latency_provenance = "measured"
        else:
            run.latency_provenance = "unknown"
        metadata = json.loads(run.measurement_metadata) if isinstance(run.measurement_metadata, str) else (run.measurement_metadata or {})
        metadata["tokens"] = {"source": "provider_reported" if reported else "unknown", "method": "executor_step_census" if reported else None, "census": census, "reason": None if reported else "executor_reported_no_token_census"}
        metadata["duration"] = {"source": "measured" if duration_ms is not None else "unknown", "method": "process_wall_clock" if duration_ms is not None else None}
        metadata["cost"] = {"source": "unknown", "reason": "opencode_route_carries_no_resolved_price"}
        run.measurement_metadata = json.dumps(metadata)
        if reported:
            await self.usage.record(session, {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "model_id": model_id,
                "requests": census["reporting_events"],
                "input_tokens": census["input"],
                "output_tokens": census["output"],
                "cached_tokens": census["cache_read"] + census["cache_write"],
                "reasoning_tokens": census["reasoning"],
                "source": "provider_reported",
                "metadata": {"reporting_events": census["reporting_events"], "reported_total": census["total"], "cache_write": census["cache_write"]},
            })
        if duration_ms is not None:
            await self.latency.record(session, {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "duration_ms": int(duration_ms),
                "source": "measured",
                "method": "process_wall_clock",
            })
        await session.commit()

    async def _dispatch_command(self, session: AsyncSession, task_id: str, workspace: WorkspaceRecord, timeout_seconds: float) -> dict:
        """Execute a deterministic command task (npm install, build, etc.) without AI model."""
        task = await session.get(OrchestrationTaskRecord, task_id)
        if not task or task.state != "planned":
            raise DomainError("resource_conflict", message="Only dependency-ready planned tasks can dispatch.")
        if task.current_run_id:
            previous_run = await session.get(TaskRun, task.current_run_id)
            if previous_run and previous_run.status in {"failed", "timed_out", "cancelled", "interrupted"}:
                task.current_run_id = None
                await session.commit()
        await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "ready")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        command = task.description.strip()
        await self.runs.create(session, run_id=run_id, prompt=f"[command] {command}", routing_mode="command", workspace_id=workspace.id, project_id=task.project_id)
        task.current_run_id = run_id
        await session.commit()
        await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "running")
        await self.runs.start(session, run_id)
        attempt = await self.runs.start_attempt(session, run_id, "command")
        chunks = []
        async def on_chunk(text, stream):
            chunks.append({"stream": stream, "content": text})
        process_id = f"cmd-{task.id}-{attempt.id}"
        receipt = await self.manager.execute_command(command, process_id, cwd=workspace.path, timeout_seconds=timeout_seconds, on_chunk=on_chunk)
        await self.output.append_many(session, run_id, chunks, attempt.id)
        await session.commit()
        status = self._status(receipt["outcome"])
        # A command task runs no model, so it has no census - but it does have a
        # measured wall clock, and a run row that records neither is a run the
        # fleet's exports cannot see.
        await self._record_run_telemetry(session, run_id, attempt.id, task_type="command", workspace_id=workspace.id, duration_ms=receipt.get("duration_ms"))
        await self.runs.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt={k: v for k, v in receipt.items() if k not in {"stdout", "stderr"}}, error_code=receipt.get("error_code"))
        await self.runs.finalize(session, run_id, status, receipt.get("error_code"))
        # Transition task state based on outcome
        if status == "completed":
            # Auto-generate acceptance evidence for command tasks (exit 0 = passed)
            acceptance = json.loads(task.acceptance_json or "[]")
            criteria_evidence = [{"criterion_id": item.get("criterion_id", f"ac-{i}"), "status": "passed", "evidence": f"Command exited with code 0 in {receipt.get('duration_ms', 0)}ms"} for i, item in enumerate(acceptance)]
            await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "completed", criteria=criteria_evidence, run_id=run_id)
        elif status in {"failed", "timed_out"}:
            await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "failed")
        return {"task_id": task.id, "run_id": run_id, "attempt_id": attempt.id, "process_id": process_id, "agent_id": None, "model": None, "task_type": "command", "status": status, "receipt": {key: receipt.get(key) for key in ("outcome", "exit_code", "error_code", "duration_ms")}, "quality_findings": [], "route_decision": {"type": "command", "reason": "Deterministic command task"}, "task_completion_claimed": status == "completed", "completion_requires_quality_evidence": False}

    async def _dispatch_ai(self, session: AsyncSession, task_id: str, workspace: WorkspaceRecord, token_limit: int | None, timeout_seconds: float) -> dict:
        """Execute an AI-generated task through a verified agent with dynamic model selection."""
        task = await session.get(OrchestrationTaskRecord, task_id)
        if not task or task.state != "planned":
            raise DomainError("resource_conflict", message="Only dependency-ready planned tasks can dispatch.")
        # The preflight gate observes the host, and the dispatcher never calls it: the
        # only callers of `build_execution_preflight` are the run API and the readiness
        # endpoints. So the one path that actually spends a provider allowance and a
        # route's standing had no host check at all, and a machine with no room bought
        # a dead attempt per dispatch. Checked here, before anything is spent - no run
        # row, no attempt, no state transition - so the task stays `planned` and is
        # dispatched unchanged once the host recovers. This refuses only a host that
        # genuinely cannot serve an allocation; pressure short of that is observed and
        # carried, not gated on. See host_capacity for why the two differ.
        host = host_capacity()
        if not host["sufficient"]:
            raise DomainError(
                "host_capacity_unavailable",
                message=host["detail"] or "This machine has no room left to host a run.",
                details={"host": host_observation(), "task_id": task_id},
            )
        workspace_root = __import__("pathlib").Path(workspace.path)
        # What acceptance measures may never be excluded from the snapshot as generated
        # output, so the write scope this attempt is judged against stays visible to the
        # clause that judges it, whatever the workspace declares about itself.
        measured = self.acceptance.measured_paths(json.loads(task.acceptance_json or "[]")) | set(self._allowed_write_scope(task))
        before = self.acceptance.snapshot(workspace_root, protected=measured)
        assignment = await self.assignment.assign(session, task_id, workspace.id)
        agent = await session.get(AgentRecord, assignment["selected_agent"]["id"])
        if not agent:
            raise DomainError("execution_unavailable", message="Assigned Agent disappeared before execution.")
        # Dynamic model selection
        route_decision = await self._select_model(session, task, agent)
        await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "ready")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        run_focus: dict = {}
        prompt = self._prompt(task, workspace.path, focus_sink=run_focus)
        await self.runs.create(session, run_id=run_id, prompt=prompt, routing_mode="orchestration", workspace_id=workspace.id, project_id=task.project_id)
        task.current_run_id = run_id
        await session.commit()
        budget_plan = await self._context_budget(session, route_decision, prompt, token_limit)
        try:
            context = await self.context.prepare(session, task_id, budget_plan["token_limit"], run_id, reserved_tokens=budget_plan["reserved_tokens"])
        except Exception:
            await self.runs.finalize(session, run_id, "failed", "context_preparation_failed")
            task_service = __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService()
            current = await session.get(OrchestrationTaskRecord, task_id)
            if current and current.state == "ready":
                await task_service.transition(session, task_id, "blocked")
                await task_service.transition(session, task_id, "planned")
            raise
        await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "running")
        await self.runs.start(session, run_id)
        selected_model = route_decision.get("model")
        selected_provider = route_decision.get("provider")
        # A route's identity is the one the registry holds it under, not a name
        # rebuilt from its parts. Rebuilding put the provider prefix back only when
        # the bare name carried no slash - and NVIDIA namespaces its model names, so
        # `nvidia/abacusai/dracarys-llama-3.1-70b-instruct` was dispatched, recorded
        # and held under `abacusai/dracarys-llama-3.1-70b-instruct`, naming a provider
        # that does not exist. Production evidence 2026-08-21: eleven consecutive
        # dispatches each spent their single probe on that phantom route and each came
        # back `executor_local_failure` - a non-measurement the route never earned -
        # while the availability hold that should have stopped the twelfth was refused
        # because no model record answers to the invented name.
        qualified_model = self._route_identity(route_decision)
        attempt = await self.runs.start_attempt(session, run_id, "agent", agent_id=agent.id, model_id=qualified_model, provider_instance_id=f"opencode:{selected_provider}" if selected_provider else None)
        chunks = []
        async def on_chunk(text, stream):
            chunks.append({"stream": stream, "content": text})
        # Build invocation with dynamically selected model
        stdin = prompt if agent.input_method == "stdin" else None
        argv = self._build_argv_with_model(agent, prompt, workspace.path, route_decision)
        step_budget, child_env = self._executor_budget(agent)
        process_id = f"orchestration-{task.id}-{attempt.id}"
        try:
            receipt = await self.manager.execute_argv(argv, process_id, cwd=workspace.path, timeout_seconds=timeout_seconds, stdin_data=stdin, on_chunk=on_chunk, env=child_env)
        except asyncio.CancelledError:
            # ProcessManager has already shielded tree cleanup. Reconcile the
            # canonical records before allowing caller cancellation to escape.
            await self.output.append_many(session, run_id, chunks, attempt.id)
            await self.runs.finalize_attempt(
                session,
                attempt.id,
                status="interrupted",
                outcome="interrupted",
                receipt={"outcome": "interrupted", "error_code": "caller_cancelled"},
                error_code="caller_cancelled",
            )
            await self.runs.finalize(session, run_id, "interrupted", "caller_cancelled")
            current_task = await session.get(OrchestrationTaskRecord, task_id)
            if current_task and current_task.state == "running":
                await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "failed")
            raise
        await self.output.append_many(session, run_id, chunks, attempt.id)
        await session.commit()
        # A provider that declined to serve the request ends the attempt with the
        # same non-zero exit as a route that tried the work and failed it. The
        # difference decides what the fleet should do next: a refused route refuses
        # the next dispatch identically, so an exit code alone buys one wasted
        # attempt per pass forever. Both `_select_model` and the capability
        # tournament already exclude a route whose allowance is spent - each reads
        # `quota_observations` - but nothing wrote that record outside a manual API
        # call, so the exclusion they implement never fired on its own. Production
        # evidence 2026-08-19: attempt-e2cd417ed8aa spent 253s reaching HTTP 403
        # `insufficient_quota`, was recorded as `non_zero_exit`, and left the dead
        # route ranked first on one ordinary failure.
        refusal = detect_provider_refusal(chunks, model=selected_model)
        if refusal and refusal["allowance_exhausted"] and selected_provider and selected_model:
            # Scoped to whichever allowance the provider actually named. A spent
            # per-model allowance is no evidence about the account's other models,
            # so it is recorded under that model - but an account whose own tier is
            # spent refuses every model on it, and `_is_exhausted` reads a `*` scope
            # as exactly that. Recording the second as the first is what made the
            # fleet rediscover one spent tier once per model: production evidence
            # 2026-08-21 has thirteen model-scoped `opencode:aliyun` observations
            # written inside two minutes from the identical account-level message,
            # each holding out one route of roughly eighty, while every NEXA
            # dispatch in that window answered 409 `execution_unavailable`.
            # Held for as long as the ledger can justify, not for a flat hour. A
            # provider that names no reset is being guessed at, and each expiry the
            # next look answers identically is that guess contradicted - so the
            # horizon is derived from the looks already taken instead of reset to the
            # same hour every time. Production evidence 2026-08-21: five consecutive
            # `opencode:aliyun` observations, each "add funds", each dated an hour
            # ahead, each costing the single probe a dispatch is allowed while five
            # ready NEXA tasks answered `execution_unavailable`.
            scope = "*" if refusal["refusal_scope"] == "provider" else selected_model
            try:
                horizon = await self.quota.refusal_horizon(
                    session, f"opencode:{selected_provider}", scope,
                    retry_after_seconds=refusal["retry_after_seconds"],
                )
                observation = await self.quota.record(session, f"opencode:{selected_provider}", {
                    "scope": scope,
                    "unit": "requests",
                    "remaining": 0,
                    "source": "measured",
                    "ttl_seconds": horizon["ttl_seconds"],
                    "evidence": {"reason": "provider_refusal", "run_id": run_id, "attempt_id": attempt.id, "horizon": horizon, **refusal},
                })
                refusal["quota_observation_id"] = observation.id
                refusal["withheld"] = horizon
            except DomainError:
                # A provider instance TEMM does not hold cannot carry an
                # observation. The refusal still belongs on the attempt's receipt,
                # which is the record this attempt is judged from.
                refusal["quota_observation_id"] = None
        process_status = self._status(receipt["outcome"])
        # Quality gates
        quality_findings = []
        checks = []
        gate_results = []
        if process_status == "completed":
            from pathlib import Path
            gate = EngineeringGateService()
            workspace_root = Path(workspace.path)
            checks = gate.discover(workspace_root)
            if checks:
                gate_results = await gate.run(self.manager, workspace_root, checks, timeout_seconds=min(timeout_seconds, 120))
                quality_findings = [{"check": r.get("kind"), "status": r.get("status"), "evidence": r.get("receipt", r.get("evidence"))} for r in gate_results]
                run = await session.get(TaskRun, run_id)
                if run:
                    import json as _json
                    existing_meta = _json.loads(run.measurement_metadata) if isinstance(run.measurement_metadata, str) else (run.measurement_metadata or {})
                    existing_meta["quality_gates"] = {"executed": len(gate_results), "passed": sum(1 for r in gate_results if r.get("status") == "passed"), "findings": quality_findings}
                    run.measurement_metadata = _json.dumps(existing_meta)
                    await session.commit()
        after = self.acceptance.snapshot(workspace_root, protected=measured)
        workspace_diff = self.acceptance.diff(before, after)
        criteria = json.loads(task.acceptance_json or "[]")
        criteria_evidence = self.acceptance.evaluate(workspace_root, criteria, workspace_diff, gate_results if process_status == "completed" and checks else [])
        task.acceptance_json = json.dumps(self.acceptance.merge_progress(criteria, criteria_evidence))
        await session.commit()
        all_satisfied = bool(criteria_evidence) and all(item["status"] == "passed" for item in criteria_evidence)
        no_effect = process_status == "completed" and not workspace_diff and any(item.get("evaluator", {}).get("type") in {"changed_files_subset", "path_exists_contains", "file_contains_excludes", "json_root_dependencies_absent", "file_exact_content"} for item in criteria)
        # An executor that consumed its whole step budget was interrupted, not
        # unproductive: the CLI disables its tools at the ceiling and forces a
        # text-only reply, then exits 0. Recording that as a plain `no_effect`
        # attributed a TEMM-side budget to the route and hid the one fact that
        # explains the empty diff, so the step census is measured from the
        # executor's own event stream and carried on the receipt.
        steps_observed = sum(chunk["content"].count('"type":"step_start"') for chunk in chunks) if step_budget else 0
        step_budget_exhausted = bool(step_budget) and steps_observed >= step_budget
        # Whether this attempt measured the route at all. A non-zero exit is also
        # what the CLI produces when it never resolved the provider, so the exit
        # code cannot distinguish a route that failed the work from one that was
        # never asked to do it - and TEMM published incapacity for the second.
        measurement = classify_measurement(
            chunks,
            outcome=receipt.get("outcome"),
            provider_refusal=refusal,
            effect_observed=bool(workspace_diff),
            acceptance_satisfied=all_satisfied,
        )
        # A served request is the one measurement that can contradict a spent
        # allowance, and nothing recorded it. Without it the horizon that lengthens
        # on each reconfirmed refusal has no way back down: an account topped up
        # after its worst hour would keep that hour's hold, and the ledger would go
        # on carrying a spent claim the fleet had already watched be false.
        if measurement["measured"] and selected_provider:
            try:
                await self.quota.note_served(session, f"opencode:{selected_provider}", model=selected_model, evidence={"run_id": run_id, "attempt_id": attempt.id})
            except DomainError:
                # A provider instance TEMM does not hold cannot carry an
                # observation, and there is nothing to correct if it never did.
                pass
        # Read the machine the moment the process ended, so a local failure has a host
        # reading beside it rather than a bare classification. Taken after exit, when
        # the executor's own pages are already released, so it understates the pressure
        # the run was actually under - which is the safe direction for a reading that
        # can only ever withhold a penalty from a route.
        host_at_exit = host_observation()
        provider_propagation = self._propagated_providers(child_env)
        # Capability evidence records what a route can do; acceptance records
        # whether one attempt produced the artifact this task asked for. Deriving
        # the first from the second published incapacity that the attempt's own
        # transcript contradicts, and because the newest execution measurement wins
        # aggregation, a single disappointing attempt de-certified the only working
        # route and made every later dispatch fail `execution_unavailable` until an
        # out-of-band probe recertified it. Neither an unsatisfied contract nor an
        # empty diff is a measurement of incapacity: production evidence collected
        # 2026-08-19 (run-bf11b33a2cfa) shows a route that read twenty files, ran
        # the workspace test suite, wrote and removed a scratch script, then
        # declined to add the contracted file because it judged the requirement
        # already met - and TEMM recorded `file_read=False` about a run built from
        # successful file reads. Declining is a judgement, not an inability. Only a
        # process that never ran proves the route cannot be exercised; a route that
        # is genuinely broken is caught by the capability probe when the TTL lapses,
        # which measures a real write instead of inferring from disappointment.
        # Attempt quality is carried separately by the attempt history behind
        # `rank()`, whose no-effect and recent-failure penalties demote a
        # weak route without hard-gating it out of selection.
        availability_hold = await self._hold_non_measured_route(session, qualified_model, measurement, run_id=run_id, attempt_id=attempt.id, provider_propagation=provider_propagation, host=host_at_exit)
        # And the other direction, from the same classification: an attempt that did
        # measure the route observed it executable, more recently and against harder
        # work than the certification that first admitted it.
        availability_renewal = await self._renew_measured_route(session, qualified_model, measurement, run_id=run_id, attempt_id=attempt.id, provider_propagation=provider_propagation)
        # Availability alone does not make a route selectable: the capability floor
        # gates it too, and it expires on the probe's clock rather than on the work's.
        # This renews the floor from the same measurement, positive direction only.
        capability_renewal = await self._renew_measured_capabilities(session, qualified_model, measurement, run_id=run_id, attempt_id=attempt.id, workspace_diff=workspace_diff)
        # Independently evaluated acceptance is the authoritative contract, not the
        # executor's exit code. An attempt that satisfied every persisted criterion
        # is complete even when the CLI exited non-zero or was stopped at the timeout
        # bound after it had already written the work. Discarding that verified
        # progress previously marked good attempts failed, which spawned an unbounded
        # "Repair incomplete work" chain instead of advancing the project.
        status = "completed" if all_satisfied else "failed" if process_status == "completed" else process_status
        # The same classification the route evidence is gated on, applied to the task.
        # `failed` is a verdict on the work, and an attempt that never measured
        # anything did not reach the work: nothing was asked of the model, nothing was
        # written, and no criterion was exercised. Recording that as a task failure
        # retires a queue entry on the strength of a condition outside the task.
        requeue_unmeasured = not all_satisfied and not measurement.get("measured") and not workspace_diff
        attempt_receipt = {k: v for k, v in receipt.items() if k not in {"stdout", "stderr"}}
        attempt_receipt.update({"workspace_binding": {"workspace_id": workspace.id, "workspace_path": workspace.path, "executor_cwd": workspace.path, "allowed_write_scope": self._allowed_write_scope(task), "permission_profile": workspace.permission_profile}, "invocation": {"executable": argv[0] if argv else None, "argv": argv, "model_argument": qualified_model, "agent_argument": next((argv[i + 1] for i, item in enumerate(argv) if item == "--agent" and i + 1 < len(argv)), None), "cwd": workspace.path, "environment_keys": sorted(os.environ), "stdin": {"provided": stdin is not None, "sha256": hashlib.sha256((stdin or "").encode()).hexdigest(), "length": len(stdin or "")}, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}, "stdout_stderr": {"stdout_length": len(receipt.get("stdout", "")), "stderr_length": len(receipt.get("stderr", "")), "stderr_tail": receipt.get("stderr", "")[-2000:], "stdout_tail": stdout_tail(chunks)}, "workspace_diff": workspace_diff, "focus_adherence": self._focus_adherence(run_focus, workspace_diff), "workspace_snapshot": self.acceptance.artifact_census(workspace_root, measured), "acceptance": criteria_evidence, "all_acceptance_satisfied": all_satisfied, "no_effect": no_effect, "executor_budget": {"step_budget": step_budget, "steps_observed": steps_observed, "exhausted": step_budget_exhausted}, "provider_refusal": refusal, "measurement": measurement, "host": host_at_exit, "availability_hold": availability_hold, "availability_renewal": availability_renewal, "capability_renewal": capability_renewal, "context_budget": {**budget_plan, "pack_id": context["pack"]["id"], "available_tokens": context["budget"]["available_tokens"], "used_tokens": context["budget"]["used_tokens"], "truncated": context["budget"]["truncated"], "excluded_source_count": len(context["budget"]["excluded"]), "excluded_sources": context["budget"]["excluded"][:MAX_RECORDED_EXCLUSIONS]}, "provider_propagation": provider_propagation, "completion_detection": {"process_outcome": receipt.get("outcome"), "effect_observed": bool(workspace_diff), "acceptance_satisfied": all_satisfied, "reason": "acceptance_satisfied" if all_satisfied else "provider_refused" if refusal else "step_budget_exhausted" if step_budget_exhausted else "no_effect" if no_effect else "acceptance_unsatisfied"}, "task_disposition": {"requeued": requeue_unmeasured, "classification": measurement.get("classification"), "reason": "non_measurement_returns_the_task_to_the_queue" if requeue_unmeasured else "attempt_reached_the_work"}})
        # A refusal names the attempt's cause more precisely than any TEMM-side
        # reading of the empty diff it left behind, so it takes precedence over
        # them: an attempt the provider never served did not exhaust a step budget
        # and did not decline to act.
        error_code = None if all_satisfied else (("provider_allowance_exhausted" if refusal["allowance_exhausted"] else "provider_credential_rejected" if refusal.get("refusal_kind") == "credential" else "provider_refused") if refusal else receipt.get("error_code") or ("step_budget_exhausted" if step_budget_exhausted else "no_effect" if no_effect else "acceptance_unsatisfied"))
        await self._record_run_telemetry(
            session, run_id, attempt.id,
            task_type=task.task_type or "implementation",
            model_id=qualified_model,
            agent_id=agent.id,
            workspace_id=workspace.id,
            duration_ms=receipt.get("duration_ms"),
            census=measurement.get("token_census"),
        )
        await self.runs.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt=attempt_receipt, error_code=error_code)
        await self.runs.finalize(session, run_id, status, error_code)
        task = await session.get(OrchestrationTaskRecord, task_id)
        if task:
            await session.refresh(task)
        if task and task.state == "running":
            if all_satisfied and status == "completed":
                await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, "completed", criteria=criteria_evidence, run_id=run_id)
            elif requeue_unmeasured:
                # Back to `planned`, at its own anchor, with its contract and revision
                # intact - the queue is where a task belongs while it is still unknown
                # whether its work passes. Retiring it instead cost more than a turn:
                # a retired task returns only as a fresh reconciliation task, which for
                # a `partial:` anchor spends one of three repair generations, and the
                # generation budget exists to bound repair recursion, not to be
                # consumed by host conditions. attempt-0144bc5d1502 is the case:
                # the CLI's own runtime aborted on `MemoryExhaustion` 31s in, exit
                # 0xC0000409, before a single model step - no events, no tokens, no
                # diff - and task-1036cd4d6fc2 left the ready queue for it.
                #
                # The run and the attempt keep their failed status and their
                # diagnostics: something did fail, and it is worth reading. What may
                # not be written down is a verdict on work that was never attempted.
                #
                # Nothing counts the requeues, and deliberately: the loop only turns
                # when a dispatch is asked for, a snapshotted ready queue cannot serve
                # the same task twice in one dispatch, and the classifications that do
                # describe a lasting condition already hold their route off for their
                # TTL. `no_execution_signal` holds nothing by design, so a host that
                # keeps failing keeps being retried - which is the intent - and the
                # receipt says `requeued` every time so the caller can see it.
                task_service = __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService()
                await task_service.transition(session, task_id, "blocked")
                await task_service.transition(session, task_id, "planned")
            else:
                target = "blocked" if process_status == "completed" else "failed" if status in {"failed", "timed_out"} else "cancelled"
                await __import__("core.ai_fleet.services.orchestration_tasks", fromlist=["OrchestrationTaskService"]).OrchestrationTaskService().transition(session, task_id, target)
        return {"task_id": task.id, "run_id": run_id, "attempt_id": attempt.id, "process_id": process_id, "agent_id": agent.id, "model": route_decision.get("model"), "task_type": task.task_type, "status": status, "context_pack_id": context["pack"]["id"], "receipt": attempt_receipt, "workspace_diff": workspace_diff, "acceptance": criteria_evidence, "all_acceptance_satisfied": all_satisfied, "no_effect": no_effect, "step_budget_exhausted": step_budget_exhausted, "quality_findings": quality_findings, "route_decision": route_decision, "task_completion_claimed": all_satisfied, "completion_requires_quality_evidence": True, "measurement": measurement}

    @staticmethod
    def _route_identity(route_decision: dict) -> Optional[str]:
        """The registry id of the selected route, or the best name available for it.

        Selection carries the record's own `model_id`, so nothing has to be inferred:
        the provider column and the id prefix agree across every OpenCode route, and a
        bare model name may itself contain a slash. The reassembly is kept only as a
        fallback for a decision that predates `model_id`, and is deliberately the
        expression it always was so such a decision behaves exactly as before.
        """
        identity = route_decision.get("model_id")
        if identity:
            return identity
        provider = route_decision.get("provider")
        model = route_decision.get("model")
        return f"{provider}/{model}" if provider and model and "/" not in model else model

    def _build_argv_with_model(self, agent: AgentRecord, prompt: str, workspace: str, route_decision: dict) -> List[str]:
        """Build CLI args with dynamically selected model and TEMM's own executor agent."""
        executable = agent.detected_path or agent.cli_command
        if not executable:
            raise ValueError(f"No executable is configured for {agent.name}.")
        model = route_decision.get("model")
        provider = route_decision.get("provider")
        # For OpenCode: dispatch into the profile TEMM declares itself, so the
        # step budget, permissions and sub-delegation policy the attempt runs
        # under are TEMM's and are recorded with the attempt. Borrowing the
        # operator's `coder` profile meant inheriting a 50-step ceiling TEMM
        # never set and could not see when the attempt came back empty.
        if agent.id == "opencode-cli" and model:
            # The CLI is asked for the identity the attempt is recorded under, from
            # the same source, so the two cannot name different routes.
            return [executable, "run", "--agent", TEMM_EXECUTOR_AGENT, "--model", self._route_identity(route_decision), "--auto", "--format", "json", prompt]
        # For other agents, use their standard invocation_args
        return build_cli_args(agent, prompt, workspace)

    def _executor_budget(self, agent: AgentRecord) -> tuple[Optional[int], Optional[dict]]:
        """Return the declared step budget and config overlay for this executor.

        Only the OpenCode CLI runs under a TEMM-declared profile, so only its
        attempts can have their step census compared against a known ceiling.
        Other executors report no budget rather than a guessed one.
        """
        if agent.id != "opencode-cli":
            return None, None
        return executor_step_budget(), executor_child_env()

    def _propagated_providers(self, child_env: Optional[dict]) -> Optional[dict]:
        """Report the provider configuration the CLI was actually pointed at.

        Read back from the profile the overlay names rather than rediscovered, so
        the receipt describes what this attempt ran under. Without it, an attempt
        that failed because its provider was unresolvable is indistinguishable
        from one whose provider was present and refused - production evidence
        2026-08-20, attempt-2204ab86ef54, had no way to show which it was.

        Credential variables are reported by name and presence only.
        """
        path = (child_env or {}).get("OPENCODE_CONFIG")
        if not path:
            return None
        try:
            document = decode_config_document(Path(path).read_text(encoding="utf-8-sig")) or {}
        except OSError:
            return None
        providers = document.get("provider") if isinstance(document.get("provider"), dict) else {}
        return {
            "config_path": path,
            "provider_ids": sorted(providers),
            "credential_env_vars": credential_env_presence(providers),
        }

    def _prompt(self, task: OrchestrationTaskRecord, workspace_path: str = "", focus_sink: Optional[dict] = None) -> str:
        """Render the executor prompt, optionally reporting the focus it stated.

        `focus_sink` is filled with the paths this prompt names as the run's work, so
        the attempt receipt can report whether the run touched them. It is an out
        parameter rather than a recomputation on purpose: the point of the reading is
        that the prompt and the receipt agree about what was asked, and two
        independent derivations of "outstanding" would be free to drift apart
        silently - which would make the evidence worse than none.
        """
        needs = json.loads(task.executor_needs_json or "{}")
        # Certification probes use a minimal direct prompt to avoid confusing
        # smaller models with meta-instructions that pollute filename choice.
        if needs.get("certification_model_id"):
            if focus_sink is not None:
                focus_sink.update({"stated": [], "basis": "certification_probe_prompt_states_no_focus"})
            return task.description.strip()
        # Production tasks state the description, then the persisted acceptance
        # criteria as concrete per-path obligations. Verbose boilerplate (full
        # criterion text, "IMPORTANT" headers, execution reminders) made models time
        # out or produce wrong artifacts in production-path evidence collected
        # 2026-08-17/18, so the contract is rendered as one terse clause per path.
        # Naming the paths only as a write boundary ("Only modify these paths") was
        # not enough: executors read that as permission rather than obligation and
        # delivered a subset - or a near-miss filename - while TEMM measured the
        # existence, size, and content of paths the executor was never told were
        # mandatory. An executor cannot satisfy a contract it cannot see.
        return "\n".join([task.description.strip(), *self._required_artifacts(task, workspace_path, focus_sink=focus_sink)])

    def _required_artifacts(self, task: OrchestrationTaskRecord, workspace_path: str = "", focus_sink: Optional[dict] = None) -> list[str]:
        """Render the persisted acceptance criteria as terse per-path obligations.

        Each evaluator contributes at most one short clause, and the rendering
        follows the evaluator's real semantics: `paths_exist` demands every path,
        while `deliverable_surface` passes on any one of its candidates and is
        therefore stated as an alternative rather than as several requirements.

        Each path also carries whether the workspace already satisfies it. TEMM
        evaluates the whole contract before the run and again after it, and stating
        the contract without that first evaluation left the executor unable to tell
        finished work from outstanding work: run-84b413517244 spent its entire
        budget curl-testing the one criterion that already passed and created none
        of the three files that did not exist.
        """
        satisfied_paths, shortfalls = self._pre_run_reading(task, workspace_path)
        mandatory: dict[str, list[str]] = {}
        alternatives: list[str] = []
        forbidden: list[str] = []

        def clauses(evaluator: dict) -> list[tuple[int, str]]:
            parts = []
            if evaluator.get("min_chars"):
                parts.append((0, f"be at least {int(evaluator['min_chars'])} characters"))
            if evaluator.get("contains"):
                parts.append((1, "contain " + ", ".join(evaluator["contains"])))
            if evaluator.get("required_any"):
                parts.append((2, "contain at least one of " + ", ".join(evaluator["required_any"])))
            if evaluator.get("excludes"):
                parts.append((3, "not contain " + ", ".join(evaluator["excludes"])))
            if evaluator.get("names"):
                parts.append((4, "not declare the dependencies " + ", ".join(evaluator["names"])))
            return parts

        def readable(parts: list[tuple[int, str]]) -> list[str]:
            # Several criteria can target one path, so clauses are ordered by kind
            # rather than by criterion order: "at least N characters and contain X"
            # reads as a requirement, the reverse reads as an afterthought.
            return list(dict.fromkeys(text for _, text in sorted(parts, key=lambda item: item[0])))

        def walk(evaluator: dict) -> None:
            kind = evaluator.get("type")
            if kind == "all_of":
                for check in evaluator.get("checks", []):
                    walk(check)
            elif kind == "path_absent":
                if evaluator.get("path"):
                    forbidden.append(evaluator["path"])
            elif kind == "deliverable_surface":
                candidates = ([evaluator["path"]] if evaluator.get("path") else []) + [str(value) for value in evaluator.get("paths", [])]
                parts = clauses(evaluator)
                sources = [str(value) for value in candidates if str(value).lower().endswith(WorkspaceAcceptanceService.SOURCE_SUFFIXES)]
                if evaluator.get("require_reachable", True) and sources:
                    # Acceptance walks the import graph from the application's entry
                    # point, so a screen nothing imports does not pass however complete
                    # it is. Left unstated this is the unseen-contract defect again:
                    # `OrdersPage.tsx` was written whole, twice, and wired in neither
                    # time, because nothing ever told the executor that wiring was part
                    # of delivering a screen.
                    #
                    # For a test the walk starts at the runner instead, so the
                    # obligation is the one the runner imposes. Stated as the
                    # application's, it asks the executor to import a test file from
                    # production code to satisfy a criterion - work no reviewer would
                    # accept, in service of a rule acceptance no longer applies.
                    if all(WorkspaceAcceptanceService.test_scoped_path(value) for value in sources):
                        parts.append((5, "be run by the project's test suite - named and placed by the test runner's own convention, so running the suite runs it"))
                    else:
                        parts.append((5, "be reachable from the application entry point - imported, directly or through the modules it imports, by the code the application already runs"))
                if len(candidates) == 1:
                    mandatory.setdefault(candidates[0], []).extend(parts)
                elif candidates:
                    alternatives.append(f"- at least one of {', '.join(candidates)}, which must " + " and ".join(readable(parts) or ["exist"]))
            elif kind == "paths_exist":
                for value in evaluator.get("paths", []):
                    mandatory.setdefault(str(value), [])
            elif kind != "changed_files_subset" and evaluator.get("path"):
                mandatory.setdefault(evaluator["path"], []).extend(clauses(evaluator))

        for criterion in json.loads(task.acceptance_json or "[]"):
            walk(criterion.get("evaluator") or {})

        forbidden_present = [
            value for value in dict.fromkeys(forbidden)
            if workspace_path and (Path(workspace_path) / value).exists()
        ]
        lines = []
        if mandatory or alternatives:
            lines.append("Acceptance is measured on these exact paths, and every one of them must be present when you stop:")
            for path, parts in mandatory.items():
                unique = readable(parts)
                # Every path carries the pre-run reading of it: satisfied, or the
                # clauses that fail right now. Left unannotated, a path failing one
                # clause of five reads exactly like a path that does not exist, and
                # the executor's own reading of the file then contradicts the
                # contract - four clauses plainly met, so nothing to do here.
                if path in satisfied_paths:
                    state = " (already satisfied)"
                elif shortfalls.get(path):
                    state = " (fails now: " + "; ".join(shortfalls[path]) + ")"
                else:
                    state = ""
                lines.append(f"- {path}{state}" + (" - must " + " and ".join(unique) if unique else ""))
            lines.extend(alternatives)
        # What the run is for, stated as work rather than left to be inferred from the
        # listing above it. A file that must not exist and still does is outstanding
        # work exactly as a missing file is. Naming only the missing deliverables sent
        # attempt-0510cc86c1cf to `client.ts` and left in place the four debris files
        # its contract also measured, which is what failed the run.
        #
        # Removals are named whether or not a deliverable is also missing. Gated on
        # there being both a satisfied and an unsatisfied deliverable, this line
        # carried them in only one of the three shapes a contract takes - and not in
        # the shape where they are the entire job. Production evidence 2026-08-21:
        # task-b0c0684775c4 listed `client.ts` and `acceptance.test.ts`, both "(already
        # satisfied)", and four debris files under a closing "must not exist" boundary;
        # with nothing outstanding the run-focus line was skipped, so the only
        # outstanding work in the task was the only work never stated as work. Three
        # dispatches read that contract and changed nothing, and `delivery:no-debris`
        # failed each time - the same criterion, and the same silence, that defect #43
        # added the removals for. The boundary line is not a substitute: this method
        # exists because executors read a stated boundary as permission and a stated
        # obligation as work.
        outstanding = [path for path in mandatory if path not in satisfied_paths]
        removals = [f"removing {value}" for value in forbidden_present]
        settled = [path for path in mandatory if path in satisfied_paths]
        # Gated on `settled`, this line was withheld from the one contract shape where
        # it is the whole of the instruction: a single outstanding deliverable and
        # nothing satisfied yet. With `settled` empty the conjunction is false however
        # much work is outstanding, so the run's objective went unstated precisely when
        # it was 100% of the run. Production evidence 2026-08-21: task-1036cd4d6fc2
        # measured one path, `frontend/src/App.tsx`, failing two clauses of a
        # navigation contract. The rendered prompt named it once, in a listing between
        # two verbatim copies of the same 29-path allowlist - 61% of the prompt against
        # the specification's 13% - and closed on "Do not modify anything outside".
        # attempt-0424a80f0a3f then read App.tsx at its eighth tool call, wrote neither
        # `Routes` nor `route` anywhere in 143 output chunks, edited one CSS file, and
        # reported the shell complete with all gates green. Four consecutive attempts
        # on this contract behaved the same way.
        #
        # `settled` was never load-bearing here: the reassurance it guards is already
        # conditioned on itself in the sentence below, so the conjunct only ever
        # suppressed the imperative. Which is the distinction this method exists to
        # draw - an executor reads a stated boundary as permission and a stated
        # obligation as work, and a contract whose only imperative is its boundary
        # gets minimal edits and a re-run of the gates that already pass.
        if focus_sink is not None:
            # Recorded whether or not the line below is emitted: "the prompt named no
            # focus" and "the prompt named a focus the run ignored" are different
            # findings, and only one of them is about the executor.
            focus_sink.update({
                "stated": list(outstanding),
                "removals": list(forbidden_present),
                "settled": list(settled),
                "basis": "run_focus_directive" if (removals or outstanding) else "contract_has_no_outstanding_path",
            })
        if removals or outstanding:
            # The preamble is only true when something actually passes; with nothing
            # satisfied the same sentence would claim a reassurance the contract does
            # not support.
            lines.append(
                ("The paths marked already satisfied pass now and need no re-checking. " if settled else "")
                + "Spend this run on: " + ", ".join([*outstanding, *removals])
            )
            # A contract that never says how it is decided gets decided by the
            # executor, and the project's own gates are the obvious candidate because
            # they are green. The task description asks it to "verify the result
            # against the persisted acceptance criteria", which reads as an
            # instruction to verify by whatever means it has.
            #
            # Production evidence 2026-08-22. attempt-e3b32fc15a52 on
            # task-c609c0ba61d0 was told `frontend/src/App.tsx` "fails now: does not
            # contain Routes; contains none of route" and "Spend this run on:
            # frontend/src/App.tsx". It spent 576s over 29 tool calls, ran typecheck,
            # both test suites, the build and `verify-e2e.js` - all passing - and
            # closed: "No source files were modified - existing valid work is
            # untouched. Following the repo's established convention, I appended a
            # verified completion section for this requirement to
            # `ACCEPTANCE_SUMMARY.md`." App.tsx was never written; the receipt reads
            # `focus_adherence.verdict: "touched_none"` and the whole diff is that
            # summary file plus a scratch script the run deleted.
            # attempt-a49c6aa7e8ac on task-b4afa6822e1f, 836s earlier the same day,
            # ended the same way against the same convention.
            #
            # Both runs were right that the application works and wrong about what
            # acceptance is. Defect #82 got the failing clauses into the prompt and
            # this is the other half of the same sentence: naming what must be true
            # without naming what reads it leaves the executor free to answer a
            # question the contract never asked. Stated here rather than in the
            # listing above because an executor reads the last imperative as the job,
            # and only when work is outstanding - on a settled contract it would
            # describe a measurement of nothing.
            lines.append(
                "Acceptance is re-measured after this run by reading the text of those files. "
                "The project's own tests, typecheck, build and scripts passing is not that measurement, "
                "and recording completion in a summary or documentation file does not satisfy any path above."
            )
        if forbidden:
            lines.append(f"These paths must not exist: {', '.join(dict.fromkeys(forbidden))}")
        scope = self._allowed_write_scope(task)
        # The restriction is a permission set, so a path an absence criterion requires
        # gone has to stay inside it: deleting a file is a change to it, and a boundary
        # that omits it forbids the deletion the contract demands two lines earlier.
        # Defect #43 corrected the scope criterion to admit those paths; this render
        # still subtracted them, so the same contract produced "Spend this run on:
        # src/feature.ts, removing debris.js" / "These paths must not exist: debris.js,
        # scratch.js" / "Do not modify anything outside: src/feature.ts". That is the
        # contradiction attempt-0510cc86c1cf resolved by leaving all four of its debris
        # files exactly where they were - the only reading of that contract its own
        # scope criterion could pass.
        #
        # The focus directive below is the opposite case and keeps the subtraction: it
        # says where to work rather than what is permitted, restricts nothing, and the
        # removals are already stated as work by the run-focus line.
        #
        # Satisfied paths come out for the reason #47 fixed one line higher, arriving
        # from the other direction. With every deliverable already passing and only
        # removals outstanding, subtracting the forbidden paths left this list equal to
        # the settled set exactly, so task-25653b8e4130 closed with "Work on
        # frontend/src/api/client.ts, backend/src/tests/acceptance.test.ts" - both
        # annotated "(already satisfied)" in the same prompt - and said nothing about
        # the four deletions that were its only outstanding criterion. The last
        # imperative the executor read pointed at work the prompt itself called
        # unnecessary, and "add supporting modules" means nothing on a contract whose
        # whole remainder is deletions. When only removals are left the list is empty
        # and the directive correctly disappears: the run-focus line already states the
        # work and "These paths must not exist" carries the boundary.
        focus = [item for item in scope if item not in forbidden and item not in settled]
        # Only a `changed_files_subset` criterion actually measures scope. Asserting
        # the restriction on every task made TEMM issue contracts it contradicted in
        # the same breath: run-09cde3917460 was told App.tsx must contain `Sidebar`
        # and `Topbar` and, two lines later, not to modify anything but App.tsx and
        # styles.css - so the components those names refer to could not be created.
        # An instruction acceptance will not check, and that cannot be obeyed without
        # failing the contract, teaches the executor to discount the whole preamble.
        if scope and any(self._scoped(criterion.get("evaluator") or {}) for criterion in json.loads(task.acceptance_json or "[]")):
            lines.append(f"Do not modify anything outside: {', '.join(scope)}")
        elif focus:
            lines.append(
                f"Work on {', '.join(focus)}. Add supporting modules under the same project only where those files import them, "
                "and leave unrelated existing work untouched."
            )
        return lines

    def _focus_adherence(self, focus: dict, workspace_diff: list[dict]) -> dict:
        """Report whether the run touched the paths its own prompt told it to work on.

        TEMM computes one focus per run, states it as "Spend this run on: X", and then
        measured only the contract - so a run that never opened X was recorded exactly
        like a run that worked on X and fell short. `effect_observed` is true for both
        as soon as any file changes, and `acceptance_unsatisfied` is the reason given
        for both. Census over the 22 directed attempts in project-23a514f0c426:
        10 touched the stated focus, 12 did not, and the three longest runs in the
        project's history are all in the second group - attempt-3486f5bdbae2 spent
        3602s and 3.8M tokens with `ActivityPage.tsx` as its sole stated focus and
        changed two new test files instead; attempt-df279e00dbda spent 3000s and
        changed nothing at all; attempt-cde42a0d2608 spent 1500s and changed only
        `backend/data/app.db`. That is 2h15m of allowance whose receipts read like
        ordinary near-misses.

        This is evidence and never a gate. It does not hold the route, does not touch
        acceptance, and does not decide requeueing: satisfying a contract by editing a
        file other than the one TEMM guessed at is legitimate - defect #63's re-export
        barrel is exactly that case - so a miss is a fact about the run, not a verdict
        on it. What it buys is the ability to tell a run that did the wrong work from
        one that did the right work badly, which the receipt could not previously do.

        Defect #76: that ability was absent for the contract shape whose directed work
        is entirely removals, and absent silently. The verdict came from `stated`, which
        holds outstanding *writes*, so a removals-only focus scored `no_focus_stated`
        and the run was recorded as one nobody directed. Production evidence 2026-08-21:
        attempt-30f37bfabca5 on task-b0c0684775c4 was told "Spend this run on: removing
        __inspect_db.cjs, removing debug-db.js, removing seed.js, removing seed-data.js",
        held all four paths inside its writable scope, spent 900s and 1.87M tokens over
        60 tool calls, deleted none of them, and wrote eight other files - four of them
        outside its scope, failing a `scope` criterion that had passed before the run.
        Its receipt reads `basis: "run_focus_directive"` beside
        `verdict: "no_focus_stated"`. Defect #47 put removals into the directive; this is
        the measurement half of the same gap, on the same task #47 was diagnosed from.
        """
        stated = list(focus.get("stated") or [])
        removals = list(focus.get("removals") or [])
        changed = {entry.get("path") for entry in workspace_diff or [] if isinstance(entry, dict)}
        # A removal is honoured only by the path being gone. Presence in the diff is the
        # wrong test for it: a run that rewrote a debris file it was told to delete
        # changed that path, and scoring the mere change as adherence would report the
        # one thing the criterion forbids as the work being done.
        deleted = {entry.get("path") for entry in workspace_diff or [] if isinstance(entry, dict) and entry.get("change") == "deleted"}
        touched = [path for path in stated if path in changed]
        untouched = [path for path in stated if path not in changed]
        removals_performed = [path for path in removals if path in deleted]
        removals_outstanding = [path for path in removals if path not in deleted]
        # Defect #76: the verdict was computed from `stated` alone, so a run whose whole
        # directive was removals reported `no_focus_stated` - the one bucket that says
        # the finding is not about the executor - while `basis` in the same dict said
        # `run_focus_directive`. Two fields built from one `focus`, contradicting each
        # other about whether anything was asked.
        #
        # Both kinds of directed work are judged here, each by its own success
        # condition, because the question this reading exists to answer is the same for
        # both: did the run do the work it was told to do. Writes stay in `stated` so a
        # deletion is never scored as an untouched path, which is what the previous
        # shape was protecting against - but the protection was built on a belief about
        # the diff that is not true. `workspace_acceptance` emits a deletion as an entry
        # with `change: "deleted"`, so a performed removal was always visible; it was
        # simply never looked at.
        directed = stated + removals
        honoured = touched + removals_performed
        if not directed:
            verdict = "no_focus_stated"
        elif not honoured:
            verdict = "touched_none"
        elif len(honoured) < len(directed):
            verdict = "touched_some"
        else:
            verdict = "touched_all"
        return {
            "stated": stated,
            "touched": touched,
            "untouched": untouched,
            "verdict": verdict,
            "basis": focus.get("basis"),
            "removals_stated": removals,
            "removals_performed": removals_performed,
            "removals_outstanding": removals_outstanding,
            "changed_path_count": len(changed),
            # Removals are subtracted for the same reason they are counted above: a path
            # the run was told to delete is directed work, so its deletion appearing
            # here would report obeying the focus as working outside it.
            "changed_outside_focus": sorted(changed - set(stated) - set(removals))[:MAX_RECORDED_EXCLUSIONS],
        }

    def _scoped(self, evaluator: dict) -> bool:
        """Report whether this criterion measures which files changed."""
        if evaluator.get("type") == "changed_files_subset":
            return True
        return any(self._scoped(check) for check in evaluator.get("checks", []))

    def _satisfied_paths(self, task: OrchestrationTaskRecord, workspace_path: str) -> set[str]:
        """Return the contract paths this workspace already satisfies, untouched.

        A path counts as satisfied only when every criterion that measures it
        passes, so one failing clause keeps the path outstanding. Scope and absence
        criteria are excluded: their paths are boundaries rather than deliverables,
        and a scope check cannot be judged before the run has changed anything.
        """
        return self._pre_run_reading(task, workspace_path)[0]

    def _pre_run_reading(self, task: OrchestrationTaskRecord, workspace_path: str) -> tuple[set[str], dict[str, list[str]]]:
        """Evaluate the contract against the untouched workspace, once.

        Returns the paths already satisfied and, for each outstanding path, the
        clauses that fail right now. Reducing this reading to a set of paths threw
        away its resolution, and a near-miss is what that loss costs:
        attempt-4e473cc679af was handed a contract whose single deliverable,
        `App.tsx`, existed, exceeded its size floor, held two of its three required
        tokens and was reachable - and missed `Routes`. The executor read the file,
        found the contract substantially met, and spent the run repairing unrelated
        escape sequences in two other measured files. Both failing criteria were one
        token wide, and TEMM knew which token before the run started.
        """
        if not workspace_path:
            return set(), {}
        criteria = [
            item for item in json.loads(task.acceptance_json or "[]")
            if item.get("evaluator") and item.get("criterion_id")
        ]
        if not criteria:
            return set(), {}
        try:
            results = self.acceptance.evaluate(Path(workspace_path), criteria, [])
        except Exception:
            # A pre-run reading is an aid to the prompt, never a gate on dispatch:
            # the same evaluation runs for real after the attempt.
            return set(), {}
        satisfied: set[str] = set()
        outstanding: set[str] = set()
        shortfalls: dict[str, list[str]] = {}
        for criterion, result in zip(criteria, results):
            evaluator = criterion.get("evaluator") or {}
            passing, failing = self._path_verdicts(evaluator, result.get("evidence") or {}, result.get("status"))
            satisfied |= passing
            outstanding |= failing
            if result["status"] == "passed":
                continue
            for path, clauses in self._shortfall_clauses(evaluator, result.get("evidence") or {}).items():
                shortfalls.setdefault(path, []).extend(clauses)
        return satisfied - outstanding, {path: list(dict.fromkeys(clauses)) for path, clauses in shortfalls.items()}

    def _shortfall_clauses(self, evaluator: dict, evidence: dict) -> dict[str, list[str]]:
        """Name what a failing criterion measures that the workspace misses now.

        Only clauses the evidence can attribute are stated, which is what keeps this
        from restating the contract: a path that does not exist yet carries no clause
        detail at all, because the evaluator never got far enough to read it and the
        listing already demands the file. So the annotation appears exactly where it
        is informative - a file that is present and still one clause short - and
        stays silent where the obligation is already plain.
        """
        kind = evaluator.get("type")
        found: dict[str, list[str]] = {}

        def note(path: object, clause: str) -> None:
            if path and clause:
                found.setdefault(str(path), []).append(clause)

        def listed(values: object) -> str:
            return ", ".join(str(value) for value in (values or []))

        if kind == "all_of":
            for check, nested in zip(evaluator.get("checks", []), evidence.get("checks") or []):
                if (nested or {}).get("status") == "passed":
                    continue
                for path, clauses in self._shortfall_clauses(check, (nested or {}).get("evidence") or {}).items():
                    found.setdefault(path, []).extend(clauses)
            return found
        path = evaluator.get("path")
        if kind in {"path_exists_contains", "file_contains_excludes"}:
            if evidence.get("missing"):
                note(path, "does not contain " + listed(evidence["missing"]))
            if evidence.get("present_but_excluded"):
                note(path, "still contains " + listed(evidence["present_but_excluded"]))
        elif kind == "json_root_dependencies_absent" and evidence.get("remaining"):
            note(path, "still declares " + listed(evidence["remaining"]))
        elif kind == "file_exact_content" and evidence.get("path_exists"):
            note(path, "does not hold the exact content required")
        elif kind == "deliverable_surface":
            # Keyed the way the listing is keyed: the first candidate. A criterion
            # with several candidates is rendered as an alternative rather than as
            # this path's obligation, so an annotation on it would never be read.
            target = path or next((str(value) for value in evaluator.get("paths", [])), None)
            min_chars = int(evaluator.get("min_chars") or 0)
            length = evidence.get("content_length")
            if min_chars and isinstance(length, int) and length < min_chars:
                note(target, f"is {length} characters, not {min_chars}")
            if evaluator.get("required_any") and isinstance(length, int) and not evidence.get("matched"):
                note(target, "contains none of " + listed(evaluator["required_any"]))
            if (evidence.get("reachability") or {}).get("status") == "unreachable":
                note(target, "is not reachable from the application entry point")
            if evidence.get("reason") == "Placeholder content":
                note(target, "reads as placeholder content rather than a deliverable")
        return found

    def _path_verdicts(self, evaluator: dict, evidence: dict, status: object) -> tuple[set[str], set[str]]:
        """Split an evaluated criterion's paths into the ones passing now and the rest.

        An `all_of` fails as a whole the moment one of its checks fails, and charging
        that verdict to every path the criterion names turns a passing sibling into
        outstanding work. `rbac:destructive-guards` measures `requireRole` in
        `customers.ts`, `products.ts` and `orders.ts`; `products.ts` has carried its
        role gate since attempt-4e473cc679af, and TEMM still told
        attempt-de1e80d8d515 to spend the run on all three. A third of a run's stated
        focus being a file that already passes is not a harmless overstatement - it
        is indistinguishable, from the executor's side, from the two paths that
        genuinely need work.

        Nested checks are evaluated eagerly and in order, one evidence entry per
        check, so an absent or unlabelled entry means the verdict is unknown; an
        unknown verdict counts as outstanding, since claiming a path passes when it
        was never read is the one error this reading must not make.
        """
        if status == "passed":
            return self._deliverable_paths(evaluator), set()
        if evaluator.get("type") == "all_of":
            passing: set[str] = set()
            failing: set[str] = set()
            nested_evidence = evidence.get("checks") or []
            for index, check in enumerate(evaluator.get("checks", []) or []):
                nested = (nested_evidence[index] if index < len(nested_evidence) else None) or {}
                inner_pass, inner_fail = self._path_verdicts(check, nested.get("evidence") or {}, nested.get("status"))
                passing |= inner_pass
                failing |= inner_fail
            return passing - failing, failing
        return set(), self._deliverable_paths(evaluator)

    def _deliverable_paths(self, evaluator: dict) -> set[str]:
        """Collect the paths an evaluator requires the workspace to hold."""
        kind = evaluator.get("type")
        if kind in {"changed_files_subset", "path_absent"}:
            return set()
        paths = {str(value) for value in evaluator.get("paths", [])}
        if evaluator.get("path"):
            paths.add(evaluator["path"])
        for check in evaluator.get("checks", []):
            paths |= self._deliverable_paths(check)
        return paths

    def _allowed_write_scope(self, task: OrchestrationTaskRecord) -> list[str]:
        paths = []
        for ref in json.loads(task.context_refs_json or "[]"):
            if ref.get("source_type") == "file" and ref.get("path"):
                paths.append(ref["path"])
            paths.extend(ref.get("paths", []))
        for criterion in json.loads(task.acceptance_json or "[]"):
            evaluator = criterion.get("evaluator", {})
            if evaluator.get("path"):
                paths.append(evaluator["path"])
            if evaluator.get("type") == "changed_files_subset":
                paths.extend(evaluator.get("paths", []))
        return list(dict.fromkeys(paths))

    def _status(self, outcome: str) -> str:
        return {"completed": "completed", "timed_out": "timed_out", "cancelled": "cancelled"}.get(outcome, "failed")


dispatcher_service = ProjectDispatcherService(None)  # This line might be problematic, but we keep it for compatibility

# Note: The original file had a dispatcher_service instance at the end.
# We'll keep it but note that it's initialized with None, which might cause issues.
# However, the original file also had this line, so we keep it for compatibility.
# In practice, the service is instantiated with a ProcessManager in the API routes.
