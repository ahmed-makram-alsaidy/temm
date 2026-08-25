import asyncio
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import uuid
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.engine.host_capacity import host_observation
from core.ai_fleet.errors import DomainError
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AgentRecord, ContextPackRecord, LatencyObservationRecord, ModelCapabilityEvidenceRecord, ModelRecord, OrchestrationCheckpointRecord, OrchestrationTaskRecord, ProjectRecord, ProjectRequirementRecord, ProviderInstanceRecord, QuotaObservationRecord, RunAttemptRecord, RunOutputChunkRecord, TaskRun, UsageObservationRecord, WorkspaceRecord
from core.ai_fleet.services.executor_capabilities import ExecutorCapabilityService
from core.ai_fleet.services.measurement import MAX_AVAILABILITY_HOLD_SECONDS, NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS, PERMANENCE_HOLD_SECONDS, PERMANENCE_ROUTE_UNSERVED
from core.ai_fleet.services.execution_policy import executable_availability_ttl_seconds
from core.ai_fleet.services.orchestration_tasks import OrchestrationTaskService
from core.ai_fleet.services import project_dispatcher
from core.ai_fleet.services.project_dispatcher import DEFAULT_CONTEXT_PACK_TOKENS, REVERIFY_CAPABILITIES, ProjectDispatcherService


def _calm_host():
    """Pin the one input these tests are not about: how busy the machine is.

    `host_capacity` reads this machine's available physical memory, and a local
    non-measurement observed under memory pressure is deliberately charged to the host
    instead of the route - the route was never asked, so withdrawing it would record
    nothing true. See `measurement.non_measurement_hold`. A test that asserts the route
    *was* held is therefore asserting something production makes conditional on the
    reading, and it decides its verdict from whatever else is running.

    Measured on this host 2026-08-22: 868 MB available against the 1024 MB abort level,
    94.6% used, with the user's own Chrome and three interactive OpenCode sessions
    holding 5.9 GB between them - and one full suite run died in an unrelated test on a
    real `MemoryError`. Two dispatcher tests flipped between runs on that alone, which
    made a genuine regression indistinguishable from a busy laptop: an unrelated patch
    was suspected for a day because reverting it happened to coincide with a calm
    moment.

    What is pinned is the input, not the behaviour. The host-attributed path has its own
    coverage in `test_host_capacity`, which builds the reading explicitly for the same
    reason.
    """
    return unittest.mock.patch.object(
        project_dispatcher,
        "host_observation",
        lambda: {**host_observation(), "pressure": False, "pressure_basis": "pinned_by_test_host_is_not_under_measurement"},
    )


class _OpenCodeStandIn:
    """The fixture agent, presenting the id that selects the OpenCode invocation branch."""

    def __init__(self, agent):
        self._agent = agent
        self.id = "opencode-cli"

    def __getattr__(self, name):
        return getattr(self._agent, name)


class ProjectDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        suffix = uuid.uuid4().hex[:8]
        self.project_id = f"dispatch-project-{suffix}"
        self.workspace_id = f"dispatch-workspace-{suffix}"
        self.requirement_id = f"dispatch-requirement-{suffix}"
        self.task_id = f"dispatch-task-{suffix}"
        self.agent_id = f"dispatch-agent-{suffix}"
        self.checkpoint_id = f"dispatch-checkpoint-{suffix}"
        self.model_id = f"dispatch-provider-{suffix}/coder"
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        async with AsyncSessionLocal() as session:
            session.add(ProjectRecord(id=self.project_id, name="Dispatch", slug=f"dispatch-{suffix}", project_type="software", owner="local"))
            session.add(WorkspaceRecord(id=self.workspace_id, name="Dispatch", path=str(self.root), permission_profile="developer", allowed_shells='["powershell"]'))
            session.add(ProjectRequirementRecord(id=self.requirement_id, project_id=self.project_id, title="Generate output", description="Run real CLI", requirement_type="functional", source_type="user", truth_state="confirmed", priority="must", status="approved", acceptance_json='[{"statement":"Output exists"}]', evidence_json="[]"))
            session.add(OrchestrationTaskRecord(id=self.task_id, project_id=self.project_id, task_type="implementation", title="Execute Python", description="Produce verified output", requirement_ids_json=json.dumps([self.requirement_id]), acceptance_json='[{"criterion_id":"output","description":"Output is verified"}]', context_refs_json=json.dumps([{"source_type":"requirement","source_id":self.requirement_id}]), executor_needs_json='{"capabilities":["coding"]}', state="planned"))
            session.add(AgentRecord(id=self.agent_id, name="AAA Python fixture", cli_command=sys.executable, detected_path=sys.executable, capabilities='["coding"]', invocation_args=json.dumps(["-c", "print('real-dispatch-output')"]), input_method="argument", output_method="stdout", working_directory="workspace", tool_kind="agent", user_enabled=True, lifecycle_status="active", discovery_state="verified", status="ready", auth_state="not_required", permission_profile="developer", discovery_source="manual"))
            session.add(OrchestrationCheckpointRecord(id=self.checkpoint_id, project_id=self.project_id, state="approved", cursor_json="{}", ready_queue_json=json.dumps([self.task_id]), active_task_ids_json="[]", lock_keys_json="[]", revision=1))
            session.add(ModelRecord(id=self.model_id, name="Dispatch coder", provider=f"dispatch-provider-{suffix}", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=__import__("datetime").datetime.utcnow(), availability_expires_at=__import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(minutes=5)))
            await session.commit()
            await ExecutorCapabilityService().certify(session, self.model_id, {"coding": True}, {"run_id": "fixture"})

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            runs = (await session.execute(select(TaskRun.id).where(TaskRun.project_id == self.project_id))).scalars().all()
            if runs:
                await session.execute(delete(UsageObservationRecord).where(UsageObservationRecord.run_id.in_(runs)))
                await session.execute(delete(LatencyObservationRecord).where(LatencyObservationRecord.run_id.in_(runs)))
                await session.execute(delete(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id.in_(runs)))
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id.in_(runs)))
                await session.execute(delete(ContextPackRecord).where(ContextPackRecord.run_id.in_(runs)))
                await session.execute(delete(TaskRun).where(TaskRun.id.in_(runs)))
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == self.model_id))
            provider_instance_id = f"opencode:{self.model_id.split('/', 1)[0]}"
            await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.provider_instance_id == provider_instance_id))
            await session.execute(delete(ProviderInstanceRecord).where(ProviderInstanceRecord.id == provider_instance_id))
            for model, condition in [(OrchestrationCheckpointRecord, OrchestrationCheckpointRecord.id == self.checkpoint_id), (OrchestrationTaskRecord, OrchestrationTaskRecord.id == self.task_id), (AgentRecord, AgentRecord.id == self.agent_id), (ProjectRequirementRecord, ProjectRequirementRecord.id == self.requirement_id), (WorkspaceRecord, WorkspaceRecord.id == self.workspace_id), (ProjectRecord, ProjectRecord.id == self.project_id)]:
                await session.execute(delete(model).where(condition))
            await session.commit()
        self.temp.cleanup()

    async def _requeue(self, session, task_id):
        """Return the fixture task to the queue so one test can dispatch it twice.

        A non-measured attempt now requeues its own task, so this reset is a no-op
        about as often as it is a transition. The fixed `-> planned` hop it replaced
        raised `resource_conflict` on exactly those attempts, which is every setup
        that arranges a launch failure or a refusal and then dispatches again.
        """
        task = await session.get(OrchestrationTaskRecord, task_id)
        if task.state == "planned":
            return
        if task.state not in {"blocked", "failed"}:
            await OrchestrationTaskService().transition(session, task_id, "blocked")
        await OrchestrationTaskService().transition(session, task_id, "planned")

    async def test_real_cancel_stops_process_preserves_cancelled_checkpoint_and_task(self):
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", "import time; print('started', flush=True); time.sleep(30)"])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            dispatch = asyncio.create_task(client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60}))
            for _ in range(100):
                async with AsyncSessionLocal() as session:
                    task = await session.get(OrchestrationTaskRecord, self.task_id)
                    run = await session.get(TaskRun, task.current_run_id) if task.current_run_id else None
                    if run and run.current_attempt_id:
                        break
                await asyncio.sleep(.05)
            else:
                self.fail("Project dispatch did not start a real attempt.")
            cancelled = await client.post(f"/api/orchestrations/{self.checkpoint_id}/cancel-executions")
            response = await asyncio.wait_for(dispatch, 10)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(response.status_code, 200, response.text)
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            run = await session.get(TaskRun, task.current_run_id)
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
        self.assertEqual(checkpoint.state, "cancelled")
        self.assertEqual(task.state, "cancelled")
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertTrue(cancelled.json()["cancelled_executions"][0]["process_cancelled"])

    async def test_real_ready_task_dispatch_persists_run_attempt_output_context_and_checkpoint(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "token_limit": 32000, "timeout_seconds": 30, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            run = await session.get(TaskRun, result["dispatched"][0]["run_id"])
            output = (await session.execute(select(RunOutputChunkRecord).where(RunOutputChunkRecord.run_id == run.id))).scalars().all()
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
        dispatched = result["dispatched"][0]
        self.assertEqual(dispatched["status"], "failed")
        self.assertFalse(dispatched["task_completion_claimed"])
        self.assertEqual(run.status, "failed")
        # The fixture prints one plain line and exits 0: an event stream with nothing in
        # it, so nothing the model did was measured and the task goes back to the queue
        # rather than out of it. The run and the attempt still read `failed`.
        self.assertEqual(task.state, "planned")
        self.assertFalse(dispatched["measurement"]["measured"])
        self.assertTrue(dispatched["receipt"]["task_disposition"]["requeued"])
        self.assertEqual(task.current_run_id, run.id)
        self.assertIn("real-dispatch-output", "".join(item.content for item in output))
        self.assertEqual(json.loads(checkpoint.ready_queue_json), [])
        self.assertTrue(dispatched["context_pack_id"].startswith("context-"))
        self.assertEqual(dispatched["receipt"]["workspace_binding"]["workspace_id"], self.workspace_id)
        self.assertEqual(dispatched["receipt"]["workspace_binding"]["executor_cwd"], str(self.root))
        self.assertEqual(dispatched["receipt"]["completion_detection"]["reason"], "acceptance_unsatisfied")

    # Two `step_finish` events in the shape `opencode --format json` really emits, so
    # the census the run row is written from is exercised end to end rather than
    # asserted in isolation. Sums: input 1662, output 416, cache 36608, total 38702.
    CENSUS_EVENTS = (
        '{"type":"step_start"}',
        '{"type":"tool","part":{"tool":"write","state":{"status":"completed"}}}',
        '{"type":"text","part":{"text":"done"}}',
        '{"type":"step_finish","part":{"id":"prt-first","tokens":{"total":37486,"input":762,"output":116,"reasoning":0,"cache":{"write":0,"read":36608}},"cost":0}}',
        '{"type":"step_finish","part":{"id":"prt-second","tokens":{"total":1216,"input":900,"output":300,"reasoning":16,"cache":{"write":0,"read":0}},"cost":0}}',
    )

    async def _use_executor_output(self, *lines: str) -> None:
        """Make the fixture executor emit an exact event stream on stdout."""
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", ";".join(f"print({line!r})" for line in lines)])
            await session.commit()

    async def _seed_large_context(self, sources: int = 4, chars: int = 40000) -> None:
        """Give the task a context scope no fixed default budget admits.

        Completeness reconciliation composes repair scopes of 26-51 files, so the pack
        a repair task asks for is routinely larger than whatever constant a caller
        happened to send.
        """
        refs = [{"source_type": "requirement", "source_id": self.requirement_id}]
        for index in range(sources):
            path = self.root / f"scope-{index}.txt"
            path.write_text("x" * chars, encoding="utf-8")
            refs.append({"source_type": "file", "workspace_id": self.workspace_id, "path": path.name})
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.context_refs_json = json.dumps(refs)
            await session.commit()

    async def _dispatch(self, **payload) -> dict:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 30, "max_tasks": 1, **payload})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["dispatched"][0]

    async def test_the_context_pack_is_budgeted_from_the_route_window_not_a_fixed_default(self):
        """A pack budget is a fact about the selected route, not about the caller.

        Production evidence 2026-08-20: with a fixed 32000-token default, every repair
        dispatch of `checkpoint-a8d3277ebe57` failed `resource_conflict` - "Context
        pack exceeds the model token budget" - before its executor launched, while the
        route in hand declared a 128000-token window. The queue held ready tasks and a
        certified route, and the fleet stalled on the size of a record the executor is
        never handed.
        """
        await self._seed_large_context()
        dispatched = await self._dispatch()
        budget = dispatched["receipt"]["context_budget"]
        self.assertEqual(budget["basis"], "route_context_window")
        self.assertEqual(budget["route_context_window"], 128000)
        self.assertEqual(budget["token_limit"], 128000)
        self.assertGreater(budget["reserved_tokens"], budget["prompt_tokens"], "The prompt and a reply allowance share the window with the pack.")
        self.assertFalse(budget["truncated"])
        self.assertEqual(budget["excluded_source_count"], 0)
        self.assertGreater(budget["used_tokens"], DEFAULT_CONTEXT_PACK_TOKENS, "This is the pack the fixed default refused to prepare.")
        self.assertTrue(dispatched["attempt_id"], "The attempt has to have run at all.")

    async def test_a_stated_ceiling_is_honoured_verbatim_and_truncates_rather_than_vetoing(self):
        """A caller that names a ceiling means it - the capability tournament keeps its
        probe packs small on purpose - and a scope that outgrows it loses its
        lowest-priority sources instead of losing the dispatch."""
        await self._seed_large_context()
        dispatched = await self._dispatch(token_limit=2000)
        budget = dispatched["receipt"]["context_budget"]
        self.assertEqual(budget["basis"], "caller_declared_ceiling")
        self.assertEqual(budget["token_limit"], 2000)
        self.assertEqual(budget["reserved_tokens"], 0)
        self.assertTrue(budget["truncated"])
        self.assertEqual(budget["excluded_source_count"], 4)
        async with AsyncSessionLocal() as session:
            run = await session.get(TaskRun, dispatched["run_id"])
        self.assertNotEqual(run.status_reason, "context_preparation_failed")
        self.assertTrue(dispatched["receipt"]["invocation"]["argv"], "The executor still ran with the truncated pack.")

    async def test_an_executed_run_records_the_model_census_and_duration_it_spent(self):
        """The run row is the only place the fleet's exports read from.

        Production evidence 2026-08-20: `run-1a2485f7a408` executed `aliyun/qwen3-max`
        for 641s across 33 steps and 139600 reported tokens, and its row carried model
        `None`, zero tokens and zero milliseconds - so `telemetry_export` silently
        excluded every execution the orchestration path ever performed. Interactive
        runs recorded all of it; only the runs doing the project's work did not.
        """
        await self._use_executor_output(*self.CENSUS_EVENTS)
        dispatched = await self._dispatch()
        async with AsyncSessionLocal() as session:
            run = await session.get(TaskRun, dispatched["run_id"])
            usage = (await session.execute(select(UsageObservationRecord).where(UsageObservationRecord.run_id == run.id))).scalars().all()
            latency = (await session.execute(select(LatencyObservationRecord).where(LatencyObservationRecord.run_id == run.id))).scalars().all()
        self.assertEqual(run.selected_model_id, self.model_id)
        self.assertEqual(run.selected_agent_id, self.agent_id)
        self.assertEqual(run.task_type, "implementation")
        self.assertEqual(run.workspace_id, self.workspace_id)
        self.assertEqual((run.input_tokens, run.output_tokens, run.cached_tokens), (1662, 416, 36608))
        self.assertEqual(run.token_provenance, "provider_reported")
        self.assertGreater(run.duration_ms, 0)
        self.assertEqual(run.latency_provenance, "measured")
        self.assertEqual(run.cost_provenance, "unknown", "An OpenCode route has no resolved price, and an absent price is not a cost of zero.")
        census = dispatched["measurement"]["token_census"]
        self.assertEqual(census["total"], 38702)
        self.assertEqual(census["reporting_events"], 2)
        self.assertEqual(len(usage), 1)
        self.assertEqual((usage[0].source, usage[0].model_id, usage[0].requests, usage[0].input_tokens, usage[0].reasoning_tokens), ("provider_reported", self.model_id, 2, 1662, 16))
        self.assertEqual(usage[0].attempt_id, dispatched["attempt_id"])
        self.assertEqual(len(latency), 1)
        self.assertEqual((latency[0].source, latency[0].duration_ms), ("measured", run.duration_ms))

    async def test_a_run_whose_executor_reported_no_census_records_unknown_not_zero_usage(self):
        """The fixture executor prints one plain line and reports no tokens. Zero
        tokens claimed as provider-reported would be a measurement nobody made."""
        dispatched = await self._dispatch()
        async with AsyncSessionLocal() as session:
            run = await session.get(TaskRun, dispatched["run_id"])
            usage = (await session.execute(select(UsageObservationRecord).where(UsageObservationRecord.run_id == run.id))).scalars().all()
        self.assertEqual(run.token_provenance, "unknown")
        self.assertEqual((run.input_tokens, run.output_tokens, run.cached_tokens), (0, 0, 0))
        self.assertEqual(usage, [], "Nothing was reported, so there is nothing to observe.")
        self.assertEqual(run.selected_model_id, self.model_id, "The route it ran is known regardless.")
        self.assertGreater(run.duration_ms, 0, "The wall clock was measured regardless.")
        self.assertEqual(json.loads(run.measurement_metadata)["tokens"]["reason"], "executor_reported_no_token_census")

    async def test_failed_task_can_return_to_planned_for_retry(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.state = "failed"
            await session.commit()
            retried = await OrchestrationTaskService().transition(session, self.task_id, "planned")
        self.assertEqual(retried.state, "planned")

    async def test_pre_attempt_terminal_run_returns_ready_task_to_planned(self):
        run_id = f"pre-attempt-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.state = "ready"
            task.current_run_id = run_id
            session.add(TaskRun(id=run_id, prompt="failed context", project_id=self.project_id, workspace_id=self.workspace_id, status="failed", status_reason="context_preparation_failed"))
            await session.commit()
            dispatcher = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
            await dispatcher._recover_orphaned_tasks(session, self.project_id)
            await session.refresh(task)
        self.assertEqual(task.state, "planned")
        self.assertEqual(task.current_run_id, run_id)

    async def test_running_task_behind_a_finished_run_is_returned_to_the_queue(self):
        """A run finalized by someone other than its dispatch must not strand the task.

        `_dispatch_ai` finalizes the run before it transitions the task, so a run
        already terminal - a restart marking it `interrupted`, a cancellation - makes
        that finalization conflict and abort the dispatch one step short of the
        transition. Dispatch admits only `planned` tasks and nothing else reclaimed a
        `running` one, so run-bb95c7c6a4c7 left task-8b69c00490e3 permanently
        undispatchable and its requirement permanently incomplete.
        """
        run_id = f"orphan-run-{uuid.uuid4().hex[:8]}"
        attempt_id = f"orphan-attempt-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.state = "running"
            task.current_run_id = run_id
            session.add(TaskRun(id=run_id, prompt="orphaned", project_id=self.project_id, workspace_id=self.workspace_id, status="interrupted", status_reason="service_restart", current_attempt_id=attempt_id))
            # Finished attempt, terminal in a state the run's own status contradicts -
            # exactly the record the stranded production task carries.
            session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="completed", outcome="timed_out", receipt_json=json.dumps({"all_acceptance_satisfied": True})))
            await session.commit()
            await ProjectDispatcherService(None)._recover_orphaned_tasks(session, self.project_id)
            await session.refresh(task)
        self.assertEqual(task.state, "planned", "A task behind a finished run must be dispatchable again.")
        self.assertEqual(task.current_run_id, run_id, "Recovery preserves the failed run as evidence.")

    async def test_task_whose_executor_is_still_writing_is_left_alone(self):
        """A run's status can run ahead of its executor, and reclaiming then double-dispatches.

        Restart recovery finalizes runs without checking process liveness, so a
        terminal run is not proof that the process it launched has stopped. The live
        attempt is the signal that it has not, and a second executor in the same
        workspace would corrupt the first one's diff.
        """
        run_id = f"live-run-{uuid.uuid4().hex[:8]}"
        attempt_id = f"live-attempt-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.state = "running"
            task.current_run_id = run_id
            session.add(TaskRun(id=run_id, prompt="still writing", project_id=self.project_id, workspace_id=self.workspace_id, status="interrupted", status_reason="service_restart", current_attempt_id=attempt_id))
            session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="running"))
            await session.commit()
            await ProjectDispatcherService(None)._recover_orphaned_tasks(session, self.project_id)
            await session.refresh(task)
        self.assertEqual(task.state, "running")

    async def test_live_run_never_reclaims_its_own_task(self):
        """Recovery runs at the head of every dispatch, so an in-flight task must survive it."""
        run_id = f"inflight-run-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.state = "running"
            task.current_run_id = run_id
            session.add(TaskRun(id=run_id, prompt="in flight", project_id=self.project_id, workspace_id=self.workspace_id, status="running"))
            await session.commit()
            await ProjectDispatcherService(None)._recover_orphaned_tasks(session, self.project_id)
            await session.refresh(task)
        self.assertEqual(task.state, "running")

    async def test_route_history_requires_accepted_task_completion(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            accepted_run = TaskRun(id=f"accepted-{uuid.uuid4().hex[:8]}", prompt="accepted", project_id=self.project_id, status="completed")
            unaccepted_run = TaskRun(id=f"unaccepted-{uuid.uuid4().hex[:8]}", prompt="unaccepted", project_id=self.project_id, status="completed")
            accepted_attempt_id = f"attempt-{uuid.uuid4().hex[:8]}"
            unaccepted_attempt_id = f"attempt-{uuid.uuid4().hex[:8]}"
            session.add_all([accepted_run, unaccepted_run])
            session.add_all([
                RunAttemptRecord(id=accepted_attempt_id, run_id=accepted_run.id, attempt_number=1, executor_type="agent", model_id="qwen3-coder-plus", status="completed", outcome="completed", receipt_json='{"duration_ms":1000}'),
                RunAttemptRecord(id=unaccepted_attempt_id, run_id=unaccepted_run.id, attempt_number=1, executor_type="agent", model_id="qwen3.7-max", status="completed", outcome="completed", receipt_json='{"duration_ms":100}'),
            ])
            accepted_task = OrchestrationTaskRecord(id=f"accepted-task-{uuid.uuid4().hex[:8]}", project_id=self.project_id, task_type="implementation", title="Accepted", acceptance_json='[{"criterion_id":"files","description":"Files changed"}]', state="completed", current_run_id=accepted_run.id)
            unaccepted_task = OrchestrationTaskRecord(id=f"unaccepted-task-{uuid.uuid4().hex[:8]}", project_id=self.project_id, task_type="implementation", title="Unaccepted", acceptance_json='[{"criterion_id":"files","description":"Files changed"}]', state="blocked", current_run_id=unaccepted_run.id)
            session.add_all([accepted_task, unaccepted_task])
            await session.commit()
            decision = await __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._select_model(session, task)
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_([accepted_task.id, unaccepted_task.id])))
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.id.in_([accepted_attempt_id, unaccepted_attempt_id])))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_([accepted_run.id, unaccepted_run.id])))
            await session.commit()
        rejected = {item["model_id"]: item for item in decision["capability_rejections"]}
        self.assertIn("aliyun/qwen3-coder-plus", rejected)
        self.assertEqual(rejected["aliyun/qwen3-coder-plus"]["reason"], "legacy_route_has_no_current_capability_evidence")

    async def test_opencode_route_options_precede_variadic_prompt(self):
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
        agent.id = "opencode-cli"
        argv = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._build_argv_with_model(agent, "repair prompt", str(self.root), {"provider": "aliyun", "model": "qwen3-coder-plus"})
        self.assertEqual(argv[1:8], ["run", "--agent", "temm-executor", "--model", "aliyun/qwen3-coder-plus", "--auto", "--format"])
        self.assertEqual(argv[-2:], ["json", "repair prompt"])

    async def test_executor_profile_declares_the_step_budget_the_cli_runs_under(self):
        """TEMM must own the executor budget instead of inheriting an unseen one.

        Dispatching into the operator's `coder` profile borrowed its `steps: 50`
        ceiling. An implementation attempt hit it after 175 file reads, was forced
        into a text-only reply before writing anything, and exited 0 - which TEMM
        recorded as a clean run with no effect and charged to the route.
        """
        from core.ai_fleet.engine.executor_profile import TEMM_EXECUTOR_AGENT, child_env, executor_step_budget, profile_document

        with tempfile.TemporaryDirectory() as directory:
            env = child_env(Path(directory))
            profile = json.loads(Path(env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))
        agent = profile["agent"][TEMM_EXECUTOR_AGENT]
        self.assertEqual(agent["steps"], executor_step_budget())
        self.assertGreater(agent["steps"], 50, "The declared budget must exceed the operator ceiling that truncated production work.")
        self.assertEqual(agent["permission"]["edit"], "allow")
        self.assertEqual(agent["permission"]["task"], "deny")
        self.assertEqual(profile_document(120)["agent"][TEMM_EXECUTOR_AGENT]["steps"], 120)

    async def test_repo_local_provider_reaches_the_profile_without_its_credential(self):
        """A provider declared in the checkout must survive the walk into isolation.

        Production evidence 2026-08-20, `run-133922d95108`: the probed route was
        declared only in the repository's own `opencode.json`. From the repository
        the CLI resolves 341 models; from the tournament's temporary workspace, 338.
        The missing three were exactly that provider's, so the attempt exited 1 in
        1.9 seconds having never reached the model.

        Propagation is therefore of the *declaration*, never the credential: the key
        stays in the child environment behind the CLI's own `{env:...}` indirection,
        the operator's global config is neither read nor written, and a block holding
        a literal secret is dropped whole rather than copied to disk.
        """
        from core.ai_fleet.engine.executor_profile import TEMM_EXECUTOR_AGENT, executor_config

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            checkout = base / "checkout"
            nested = checkout / "packages" / "app"
            nested.mkdir(parents=True)
            operator_root = base / "appdata" / "opencode"
            operator_root.mkdir(parents=True)
            operator_config = operator_root / "opencode.json"
            operator_config.write_text(json.dumps({"provider": {"operator-only": {"options": {"apiKey": "sk-operator-literal-1234567890"}}}}), encoding="utf-8")
            # A BOM, a line comment whose marker also occurs inside a URL, and a
            # trailing comma. The repository config this exists to propagate carries
            # all three, and the CLI reads it regardless.
            (checkout / "opencode.json").write_text(
                "\ufeff{\n"
                '  // custom route the operator added to this checkout only\n'
                '  "provider": {\n'
                '    "repo-local-router": {\n'
                '      "npm": "@ai-sdk/openai-compatible",\n'
                '      "options": {"baseURL": "https://router.example/v1", "apiKey": "{env:REPO_LOCAL_ROUTER_KEY}"},\n'
                '      "models": {"custom-coder": {"name": "Custom coder"}},\n'
                "    },\n"
                "  },\n"
                "}\n",
                encoding="utf-8",
            )
            # `authHeader` matches no credential-naming rule, so only the backstop
            # that compares against the environment can catch it.
            (nested / "opencode.jsonc").write_text(json.dumps({"provider": {"literal-secret-router": {"options": {"authHeader": "Bearer zz-literal-secret-value"}}}}), encoding="utf-8")
            profile_directory = base / "state" / "executor"
            operator_bytes = operator_config.read_bytes()
            overlay = {
                "APPDATA": str(base / "appdata"),
                "REPO_LOCAL_ROUTER_KEY": "sk-child-environment-only-9876543210",
                "AI_FLEET_TEST_AUTH_TOKEN": "Bearer zz-literal-secret-value",
            }
            with unittest.mock.patch.dict(os.environ, overlay, clear=False):
                environment, propagation = executor_config(profile_directory, 200, nested)
            profile_path = Path(environment["OPENCODE_CONFIG"])
            raw = profile_path.read_text(encoding="utf-8")
            profile = json.loads(raw)
            operator_unchanged = operator_config.read_bytes() == operator_bytes

        providers = profile.get("provider") or {}
        self.assertIn("repo-local-router", providers, "A provider the CLI would have resolved from the checkout must reach the profile.")
        self.assertEqual(providers["repo-local-router"]["options"]["baseURL"], "https://router.example/v1")
        self.assertEqual(providers["repo-local-router"]["options"]["apiKey"], "{env:REPO_LOCAL_ROUTER_KEY}", "The indirection is propagated; the value it names is not.")
        self.assertEqual(sorted(providers["repo-local-router"]["models"]), ["custom-coder"])
        self.assertIn(TEMM_EXECUTOR_AGENT, profile["agent"], "Propagating providers must not displace TEMM's own agent declaration.")
        self.assertNotIn("sk-child-environment-only-9876543210", raw, "No credential value may be written to the profile.")
        self.assertNotIn("zz-literal-secret-value", raw)
        self.assertNotIn("sk-operator-literal-1234567890", raw)
        self.assertNotIn("literal-secret-router", providers, "A block holding a literal secret is dropped whole, not sanitised in place.")
        self.assertNotIn("operator-only", providers, "The operator's global config is the CLI's to merge, not TEMM's to copy.")
        self.assertTrue(operator_unchanged, "Propagation must never write to the operator's own configuration.")
        self.assertIn({"name": "REPO_LOCAL_ROUTER_KEY", "present": True}, propagation["credential_env_vars"], "The receipt must name the variable, and only say whether it is set.")
        self.assertEqual(propagation["provider_ids"], ["repo-local-router"])
        self.assertEqual([entry["provider"] for entry in propagation["dropped_literal_credentials"]], ["literal-secret-router"])
        self.assertNotIn("zz-literal-secret-value", json.dumps(propagation))

    async def test_dispatch_gives_the_isolated_executor_a_provider_only_the_checkout_declares(self):
        """The end-to-end claim: isolation is preserved and the provider still resolves.

        The child runs with its cwd inside the measured workspace, which has no
        ancestry to the checkout the provider is declared in - the exact condition
        under which `attempt-2204ab86ef54` lost its provider. It must still see the
        provider, the profile must live outside the workspace so it cannot ship
        inside the deliverable, and the credential must reach the child only through
        the environment it always lived in.
        """
        from core.ai_fleet.engine.executor_profile import child_env, executor_step_budget

        probe = "; ".join([
            "import json, os, pathlib",
            "path = os.environ.get('OPENCODE_CONFIG') or ''",
            "raw = pathlib.Path(path).read_text(encoding='utf-8-sig') if path else ''",
            "document = json.loads(raw) if raw else {}",
            "key = os.environ.get('REPO_LOCAL_ROUTER_KEY') or ''",
            "pathlib.Path('resolved.json').write_text(json.dumps({'config_path': path, 'cwd': os.getcwd(), 'providers': sorted((document.get('provider') or {}).keys()), 'profile_holds_key': bool(key) and key in raw, 'key_in_environment': bool(key)}), encoding='utf-8')",
        ])
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "resolved", "description": "The executor resolved the repo-local provider.", "evaluator": {"type": "path_exists_contains", "path": "resolved.json", "contains": ["repo-local-router"]}},
            ])
            await session.commit()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            checkout = base / "checkout"
            checkout.mkdir(parents=True)
            (checkout / "opencode.json").write_text(json.dumps({"provider": {"repo-local-router": {"npm": "@ai-sdk/openai-compatible", "options": {"baseURL": "https://router.example/v1", "apiKey": "{env:REPO_LOCAL_ROUTER_KEY}"}, "models": {"custom-coder": {}}}}}), encoding="utf-8")
            overlay = {
                "TEMM_STATE_DIR": str(base / "state"),
                "TEMM_PROVIDER_CONFIG_ROOT": str(checkout),
                "REPO_LOCAL_ROUTER_KEY": "sk-child-environment-only-9876543210",
            }
            transport = httpx.ASGITransport(app=app)
            with unittest.mock.patch.dict(os.environ, overlay, clear=False), \
                 unittest.mock.patch.object(ProjectDispatcherService, "_executor_budget", lambda self, agent: (executor_step_budget(), child_env())), \
                 unittest.mock.patch.object(ProjectDispatcherService, "_build_argv_with_model", lambda self, agent, prompt, workspace, route: [sys.executable, "-c", probe]):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
            self.assertEqual(response.status_code, 200, response.text)
            dispatched = response.json()["dispatched"][0]
            resolved = json.loads((self.root / "resolved.json").read_text(encoding="utf-8"))
            profile_path = Path(resolved["config_path"]).resolve()
            profile_under_state = profile_path.is_relative_to((base / "state").resolve())

        propagation = dispatched["receipt"]["provider_propagation"]
        self.assertEqual(resolved["providers"], ["repo-local-router"], "The isolated executor must resolve the provider declared only in the checkout.")
        self.assertEqual(Path(resolved["cwd"]).resolve(), self.root, "Isolation is not traded away for resolution: the cwd stays the measured workspace.")
        self.assertTrue(resolved["key_in_environment"], "The credential reaches the child the way it always did - through the environment.")
        self.assertFalse(resolved["profile_holds_key"], "It must not also reach it through a file TEMM wrote.")
        self.assertTrue(profile_under_state, "The profile belongs to TEMM's state directory, not the workspace under measurement.")
        self.assertFalse(profile_path.is_relative_to(self.root), "A config inside the workspace would ship in the deliverable.")
        self.assertEqual(list(self.root.glob("opencode.js*")), [], "No configuration may be left in the measured workspace.")
        self.assertEqual(propagation["provider_ids"], ["repo-local-router"], "The receipt must record which providers the attempt actually ran under.")
        self.assertEqual(propagation["credential_env_vars"], [{"name": "REPO_LOCAL_ROUTER_KEY", "present": True}])
        self.assertNotIn("sk-child-environment-only-9876543210", json.dumps(dispatched))
        self.assertTrue(dispatched["receipt"]["all_acceptance_satisfied"])

    async def test_step_budget_exhaustion_is_reported_as_interruption_not_no_effect(self):
        """An executor cut off at its ceiling was interrupted, not unproductive.

        Both outcomes leave an empty diff and exit 0, so reporting them alike hid
        the only fact that explains the missing work and blamed the route for a
        bound TEMM itself set.
        """
        budget = 3
        script = ";".join([
            "import sys",
            f"sys.stdout.write('{chr(123)}\"type\":\"step_start\"{chr(125)}' * {budget})",
        ])
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", script])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "contracted", "description": "Contracted artifact exists.", "evaluator": {"type": "path_exists_contains", "path": "contracted.txt", "contains": ["value"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        with unittest.mock.patch.object(ProjectDispatcherService, "_executor_budget", lambda self, agent: (budget, None)), \
             unittest.mock.patch.object(ProjectDispatcherService, "_build_argv_with_model", lambda self, agent, prompt, workspace, route: [sys.executable, "-c", script]):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        self.assertTrue(dispatched["step_budget_exhausted"])
        self.assertEqual(dispatched["receipt"]["executor_budget"], {"step_budget": budget, "steps_observed": budget, "exhausted": True})
        self.assertEqual(dispatched["receipt"]["completion_detection"]["reason"], "step_budget_exhausted")

    async def test_allowed_write_scope_is_derived_from_acceptance(self):
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([{"criterion_id": "scope", "description": "Scoped", "evaluator": {"type": "changed_files_subset", "paths": ["a.txt", "b.txt"]}}])
        dispatcher = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
        self.assertEqual(dispatcher._allowed_write_scope(task), ["a.txt", "b.txt"])
        self.assertIn("Do not modify anything outside: a.txt, b.txt", dispatcher._prompt(task, str(self.root)))

    async def test_prompt_states_the_acceptance_obligation_not_only_the_write_boundary(self):
        """The executor must be told which paths acceptance measures, and what they must hold.

        Naming the paths only as a permission boundary let executors deliver a
        subset while TEMM failed them against obligations they were never shown.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "wiring", "evaluator": {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["ordersRouter"]}},
            {"criterion_id": "screen", "evaluator": {"type": "deliverable_surface", "path": "frontend/src/pages/OrdersPage.tsx", "min_chars": 1800, "required_any": ["/api/orders"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debug-db.js"}]}},
        ])
        prompt = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._prompt(task, str(self.root))
        lines = prompt.splitlines()
        obligation = next(line for line in lines if line.startswith("- frontend/src/pages/OrdersPage.tsx"))
        must_not_exist = next(line for line in lines if line.startswith("These paths must not exist:"))
        boundary = next(line for line in lines if line.startswith(("Do not modify anything outside:", "Work on ")))
        self.assertIn("at least 1800 characters", obligation)
        self.assertIn("/api/orders", obligation)
        self.assertIn("ordersRouter", next(line for line in lines if line.startswith("- backend/src/app.ts")))
        self.assertIn("debug-db.js", must_not_exist)
        self.assertNotIn("debug-db.js", boundary, "A path that must not exist is not a writable path.")

    async def test_the_measured_boundary_permits_the_deletion_it_demands(self):
        """Defect #60: a boundary omitting a path the contract requires gone forbids the deletion.

        `changed_files_subset` counts a deletion as a change to the deleted path, so the
        restriction is a permission set and has to name the debris. Defect #43 corrected
        the scope criterion to admit those paths; this render still subtracted them, so
        the executor got three consecutive lines saying remove it, it must be gone, and
        do not touch it. attempt-0510cc86c1cf resolved exactly that reading by leaving
        all four of its debris files in place - the only reading its own scope criterion
        could pass - and `delivery:no-debris` failed again.

        The soft focus directive is the other case and still omits them, which the test
        above asserts: it says where to work rather than what is permitted, and the
        removals are already stated as work by the run-focus line.
        """
        (self.root / "debris.js").write_text("// scratch", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "feature", "evaluator": {"type": "path_exists_contains", "path": "src/feature.ts", "contains": ["handle"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debris.js"}]}},
            {"criterion_id": "bounded", "evaluator": {"type": "changed_files_subset", "paths": ["src/feature.ts", "debris.js"]}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        boundary = next(line for line in lines if line.startswith("Do not modify anything outside:"))
        self.assertIn("debris.js", boundary, "Deleting a file is a change to it, so the permission set must name it.")
        self.assertIn("debris.js", next(line for line in lines if line.startswith("These paths must not exist:")))

    async def test_prompt_counts_debris_that_still_exists_as_outstanding_work(self):
        """Removals belong in the run's to-do list, not only in a prohibition.

        The outstanding-work hint exists because a contract stated without its pre-run
        evaluation cannot tell finished work from work still to do. It listed missing
        deliverables only, so attempt-0510cc86c1cf was pointed at `client.ts` while the
        four debris files its contract also measured stayed exactly where they were.
        """
        (self.root / "done.ts").write_text("export const done = 1;\n", encoding="utf-8")
        (self.root / "debug-db.js").write_text("console.log('scratch');\n", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "done", "evaluator": {"type": "paths_exist", "paths": ["done.ts"]}},
            {"criterion_id": "todo", "evaluator": {"type": "paths_exist", "paths": ["missing.ts"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debug-db.js"}, {"type": "path_absent", "path": "never-created.js"}]}},
        ])
        prompt = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._prompt(task, str(self.root))
        hint = next(line for line in prompt.splitlines() if line.startswith("The paths marked already satisfied"))
        self.assertIn("missing.ts", hint)
        self.assertIn("removing debug-db.js", hint, "A file that must not exist and still does is outstanding work.")
        self.assertNotIn("never-created.js", hint, "Nothing to spend the run on: that path is already absent.")
        self.assertNotIn("done.ts", hint.split("Spend this run on:")[1])

    async def test_debris_is_the_whole_run_when_every_deliverable_already_passes(self):
        """Removals are outstanding work whether or not a deliverable is also missing.

        The run-focus line carried the removals, but only where the contract held both
        a satisfied and an unsatisfied deliverable - one of the three shapes a
        contract takes, and not the shape where deletion is the entire job.
        Production evidence 2026-08-21: task-b0c0684775c4 listed `client.ts` and
        `acceptance.test.ts`, both already satisfied, and four debris files under a
        closing "must not exist" boundary. With nothing outstanding the focus line was
        skipped, so the only work left in the task was the only work never stated as
        work; three dispatches read that contract and changed nothing, and
        `delivery:no-debris` failed every time.
        """
        (self.root / "done.ts").write_text("export const done = 1;", encoding="utf-8")
        (self.root / "seed.js").write_text("// scratch", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "done", "evaluator": {"type": "paths_exist", "paths": ["done.ts"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "seed.js"}, {"type": "path_absent", "path": "seed-data.js"}]}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        focus = next(line for line in lines if "Spend this run on:" in line)
        spend = focus.split("Spend this run on:")[1]
        self.assertIn("removing seed.js", spend, "The debris is the only outstanding work this contract has.")
        self.assertNotIn("seed-data.js", spend, "Nothing to spend the run on: that path is already absent.")
        self.assertNotIn("done.ts", spend, "A satisfied deliverable is not work.")
        self.assertTrue(focus.startswith("The paths marked already satisfied"), focus)

    async def test_the_closing_focus_directive_never_points_at_already_satisfied_paths(self):
        """Defect #82: the twin of #47, one line lower and from the other direction.

        The closing directive is built as scope-minus-forbidden, so on a contract whose
        deliverables all pass and whose only outstanding work is deletions that list
        equals the settled set exactly. Production evidence 2026-08-22:
        task-25653b8e4130 closed on "Work on frontend/src/api/client.ts,
        backend/src/tests/acceptance.test.ts" - both annotated "(already satisfied)" in
        the same prompt - and named none of the four deletions that were its only
        outstanding criterion. 53.5% of that prompt concerned paths it declared
        already-passing against 13.9% on the removals, and the last imperative the
        executor read pointed at the former. attempt-d2389464cdd4 performed zero of the
        four removals, changed seven unrelated files, and `delivery:no-debris` failed on
        all four checks.

        The line is a focus directive, so it may only name work that is outstanding. When
        the removals are the whole of the outstanding work it has nothing to say and is
        correctly suppressed: the run-focus line states the work, and "These paths must
        not exist" carries the boundary.
        """
        service = ProjectDispatcherService(None)
        (self.root / "done.ts").write_text("export const handle = 1;", encoding="utf-8")
        (self.root / "seed.js").write_text("// scratch", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        satisfied = {"criterion_id": "done", "evaluator": {"type": "path_exists_contains", "path": "done.ts", "contains": ["handle"]}}
        debris = {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "seed.js"}]}}
        task.acceptance_json = json.dumps([satisfied, debris])

        lines = service._prompt(task, str(self.root)).splitlines()
        self.assertIn(" (already satisfied)", next(line for line in lines if line.startswith("- done.ts")))
        self.assertIn("removing seed.js", next(line for line in lines if "Spend this run on:" in line))
        self.assertFalse(
            [line for line in lines if line.startswith("Work on ")],
            "Deleting seed.js is the whole run; a directive naming only the satisfied path contradicts it.",
        )

        # With real deliverable work outstanding the directive has something to say, and
        # says only that - the satisfied path stays out of it rather than padding it.
        task.acceptance_json = json.dumps([
            satisfied,
            {"criterion_id": "todo", "evaluator": {"type": "path_exists_contains", "path": "src/feature.ts", "contains": ["handle"]}},
            debris,
        ])
        guidance = next(line for line in service._prompt(task, str(self.root)).splitlines() if line.startswith("Work on "))
        self.assertIn("src/feature.ts", guidance)
        self.assertNotIn("done.ts", guidance, "A satisfied deliverable is not where the run should spend itself.")
        self.assertNotIn("seed.js", guidance, "A path that must not exist is not a path to work on.")

    async def test_a_contract_with_nothing_satisfied_still_names_its_removals(self):
        """A removal is never in the listing the focus line would otherwise restate.

        With no deliverable satisfied the mandatory listing already names every path,
        so the deliverable half of this line restates it rather than narrowing it. The
        paths that must stop existing appear nowhere in that listing, and a closing "must not exist" boundary is the passive form
        this method exists to avoid: executors read a boundary as permission and an
        obligation as work. So the removals are named while the deliverables carry
        themselves, and the reassurance about satisfied paths is withheld because
        there are none to reassure about.
        """
        (self.root / "debug-db.js").write_text("// scratch", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "todo", "evaluator": {"type": "paths_exist", "paths": ["missing.ts"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debug-db.js"}]}},
        ])
        prompt = ProjectDispatcherService(None)._prompt(task, str(self.root))
        focus = next(line for line in prompt.splitlines() if "Spend this run on:" in line)
        self.assertIn("removing debug-db.js", focus)
        self.assertIn("missing.ts", focus)
        self.assertTrue(focus.startswith("Spend this run on:"), "Nothing passes, so the line claims nothing does.")
        self.assertNotIn("already satisfied", prompt)

    async def test_write_boundary_is_absolute_only_when_acceptance_measures_scope(self):
        """A contract TEMM does not check must not be stated as a prohibition.

        Demanding that App.tsx contain `Sidebar` while forbidding every file but
        App.tsx made the two halves of one prompt contradict each other: the
        component the criterion names cannot be created inside the boundary.
        """
        service = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        unscoped = [{"criterion_id": "navigation", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/App.tsx", "contains": ["Sidebar"]}}]
        task.acceptance_json = json.dumps(unscoped)
        lines = service._prompt(task, str(self.root)).splitlines()
        self.assertFalse([line for line in lines if line.startswith("Do not modify anything outside:")])
        guidance = next(line for line in lines if line.startswith("Work on "))
        self.assertIn("frontend/src/App.tsx", guidance)

        task.acceptance_json = json.dumps([*unscoped, {"criterion_id": "scope", "evaluator": {"type": "changed_files_subset", "paths": ["frontend/src/App.tsx"]}}])
        scoped_lines = service._prompt(task, str(self.root)).splitlines()
        boundary = next(line for line in scoped_lines if line.startswith("Do not modify anything outside:"))
        self.assertIn("frontend/src/App.tsx", boundary)

    async def test_prompt_states_how_acceptance_is_measured_beside_the_work_it_directs(self):
        """A contract that never says how it is decided gets decided by the executor.

        Defect #83: the prompt names the paths, the clauses failing right now and the
        run's focus, and says nothing about what performs the measurement. The
        executor supplies one - the project's own suite, which is green - and records
        the requirement complete without opening the file.

        Production evidence 2026-08-22. attempt-e3b32fc15a52 on task-c609c0ba61d0 was
        told `frontend/src/App.tsx` "fails now: does not contain Routes; contains none
        of route" and "Spend this run on: frontend/src/App.tsx". It spent 576s over 29
        tool calls, ran typecheck, both suites, the build and `verify-e2e.js`, and
        closed: "No source files were modified - existing valid work is untouched.
        Following the repo's established convention, I appended a verified completion
        section for this requirement to `ACCEPTANCE_SUMMARY.md`." Its
        `focus_adherence.verdict` is `touched_none` and its entire diff is that
        summary file. attempt-a49c6aa7e8ac on task-b4afa6822e1f had ended the same way
        hours earlier, so this is the shape two of the project's three outstanding
        requirements are blocked in.

        The statement sits with the imperative, because an executor reads the last
        imperative as the job, and only where there is work: on a settled contract it
        would describe a measurement of nothing.
        """
        (self.root / "frontend" / "src").mkdir(parents=True, exist_ok=True)
        app = self.root / "frontend" / "src" / "App.tsx"
        app.write_bytes(b"export default function App() { return null; }")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "shell:navigation", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/App.tsx", "contains": ["Routes"]}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        focus_index = next(index for index, item in enumerate(lines) if "Spend this run on:" in item)
        measurement = next((item for item in lines if "re-measured after this run" in item), None)
        self.assertIsNotNone(measurement, str(lines))
        self.assertEqual(
            lines.index(measurement), focus_index + 1,
            "Separated from the imperative it reads as preamble, which is how the two runs above read it.",
        )
        self.assertIn("reading the text of those files", measurement)
        self.assertIn("is not that measurement", measurement)
        self.assertIn("summary or documentation file", measurement)

        # Nothing outstanding, so no focus is stated and there is no directed work for
        # a measurement claim to attach to.
        app.write_bytes(b"Routes")
        settled = ProjectDispatcherService(None)._prompt(task, str(self.root))
        self.assertNotIn("Spend this run on:", settled)
        self.assertNotIn("re-measured after this run", settled)

    async def test_prompt_states_that_a_surface_must_be_reachable(self):
        """Acceptance walks the import graph, so the prompt must say so.

        `OrdersPage.tsx` was written whole and wired in neither attempt: nothing in
        the contract said that a screen no module imports is not a delivered screen.
        Tightening the evaluator without stating the obligation would only reproduce
        the unseen-contract defect on a new criterion.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        service = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
        task.acceptance_json = json.dumps([
            {"criterion_id": "screen", "evaluator": {"type": "deliverable_surface", "path": "frontend/src/pages/OrdersPage.tsx", "min_chars": 1800, "required_any": ["/api/orders"]}},
        ])
        obligation = next(line for line in service._prompt(task, str(self.root)).splitlines() if line.startswith("- frontend/src/pages/OrdersPage.tsx"))
        self.assertIn("reachable from the application entry point", obligation)
        self.assertIn("at least 1800 characters", obligation, "The size obligation must survive alongside it.")

        # An HTML page is the entry point rather than a module reached from one, and
        # the evaluator does not judge its reachability, so the prompt must not ask.
        task.acceptance_json = json.dumps([
            {"criterion_id": "page", "evaluator": {"type": "deliverable_surface", "path": "frontend/index.html", "min_chars": 200}},
        ])
        self.assertNotIn("reachable from the application entry point", service._prompt(task, str(self.root)))

    async def test_prompt_asks_a_test_to_be_run_by_the_suite_not_imported_by_the_app(self):
        """The obligation stated has to be the one acceptance measures.

        Production evidence 2026-08-21, attempt-18a944ee9c04: the contract for
        `backend/src/tests/orders.test.ts` told a 347-second run to make a test file
        reachable from the application entry point. That is the wrong instruction
        twice over - production code importing a test is work no reviewer would take,
        and acceptance now walks the runner's graph for a test anyway. The executor
        acts on what the prompt says, so the two have to say the same thing.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        service = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
        task.acceptance_json = json.dumps([
            {"criterion_id": "executable-proof", "evaluator": {"type": "deliverable_surface", "path": "backend/src/tests/orders.test.ts", "min_chars": 1000, "required_any": ["stock"]}},
        ])
        obligation = next(line for line in service._prompt(task, str(self.root)).splitlines() if line.startswith("- backend/src/tests/orders.test.ts"))
        self.assertIn("be run by the project's test suite", obligation)
        self.assertNotIn("reachable from the application entry point", obligation, "Nothing in an application imports its own tests.")
        self.assertIn("at least 1000 characters", obligation, "The rest of the contract is unchanged.")

    async def test_alternative_surface_paths_are_stated_as_alternatives(self):
        """`deliverable_surface` passes on any one candidate, so the prompt must not demand all."""
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "surface", "evaluator": {"type": "deliverable_surface", "paths": ["frontend/src/App.tsx", "src/App.jsx"], "min_chars": 1000, "required_any": ["login"]}},
        ])
        prompt = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._prompt(task, str(self.root))
        self.assertIn("at least one of frontend/src/App.tsx, src/App.jsx", prompt)
        self.assertNotIn("- src/App.jsx", prompt)

    async def test_prompt_states_which_contract_paths_the_workspace_already_satisfies(self):
        """A bounded run must be able to tell finished work from outstanding work.

        TEMM evaluates the contract before the run and again after it, but stated
        only the contract: run-84b413517244 was handed four mandatory paths with no
        reading attached, spent its whole 190s budget re-verifying the one criterion
        the workspace already satisfied, and created none of the three missing files.
        """
        (self.root / "backend" / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "backend" / "src" / "app.ts").write_text("app.use('/api/auth', authRouter)", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "auth:backend", "evaluator": {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["authRouter"]}},
            {"criterion_id": "auth:login-screen", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/pages/LoginPage.tsx", "contains": ["password"]}},
            {"criterion_id": "auth:session", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/auth/AuthProvider.tsx", "contains": ["logout"]}},
        ])
        service = ProjectDispatcherService(None)
        lines = service._prompt(task, str(self.root)).splitlines()
        satisfied = next(line for line in lines if line.startswith("- backend/src/app.ts"))
        outstanding = next(line for line in lines if line.startswith("- frontend/src/pages/LoginPage.tsx"))
        focus = next(line for line in lines if line.startswith("The paths marked already satisfied"))
        self.assertIn("already satisfied", satisfied)
        self.assertIn("authRouter", satisfied, "A satisfied path still states what it must hold.")
        self.assertNotIn("already satisfied", outstanding)
        self.assertIn("frontend/src/pages/LoginPage.tsx", focus)
        self.assertIn("frontend/src/auth/AuthProvider.tsx", focus)
        self.assertNotIn("backend/src/app.ts", focus)

    async def test_a_fresh_contract_states_its_work_without_claiming_anything_passes(self):
        """Nothing satisfied is not a reason to withhold the run's objective.

        This test used to assert the opposite, on the reasoning that naming outstanding
        paths is only informative once some path is done, and that on an untouched
        workspace - where every path is outstanding - singling them out would restate
        the contract as if part of it had been dropped. The first half is about
        narrowing, and narrowing is only possible when the focus list is a strict
        subset, which is exactly the case where the line was already emitted. When
        outstanding is the whole contract nothing is dropped by saying so: it is the
        same listing in the imperative mood, and mood is the entire point of the line.
        The sibling removals test conceded as much - an executor reads a boundary as
        permission and an obligation as work.

        Production decided it. task-1036cd4d6fc2 measured one path against two clauses
        and had nothing satisfied, so the imperative was withheld and the only
        instruction left in the prompt was the boundary that closed it.
        attempt-0424a80f0a3f read the path, wrote none of what the clauses asked for,
        edited a file no criterion measured and reported the work complete.

        Redundant when the listing is long, decisive when it is one line: the reassurance
        is what stays conditional, because with nothing satisfied there is nothing to be
        reassured about.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "one", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/pages/LoginPage.tsx", "contains": ["password"]}},
            {"criterion_id": "two", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/auth/AuthProvider.tsx", "contains": ["logout"]}},
        ])
        prompt = ProjectDispatcherService(None)._prompt(task, str(self.root))
        focus = next(line for line in prompt.splitlines() if "Spend this run on:" in line)
        self.assertNotIn("already satisfied", prompt)
        self.assertTrue(focus.startswith("Spend this run on:"), focus)
        self.assertIn("frontend/src/pages/LoginPage.tsx", focus)
        self.assertIn("frontend/src/auth/AuthProvider.tsx", focus)

    async def test_partially_satisfied_path_stays_outstanding(self):
        """One failing clause keeps its path outstanding, however many pass.

        A file can exist and still miss the string acceptance measures, and calling
        that path finished would tell the executor to skip the only work left in it.
        """
        (self.root / "frontend" / "src" / "auth").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend" / "src" / "auth" / "AuthProvider.tsx").write_text("export const AuthProvider = () => null", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "exists", "evaluator": {"type": "paths_exist", "paths": ["frontend/src/auth/AuthProvider.tsx"]}},
            {"criterion_id": "logout", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/auth/AuthProvider.tsx", "contains": ["logout"]}},
        ])
        service = ProjectDispatcherService(None)
        self.assertEqual(service._satisfied_paths(task, str(self.root)), set())
        self.assertNotIn("already satisfied", service._prompt(task, str(self.root)))

    async def test_present_deliverable_names_the_clause_it_falls_short_of(self):
        """A file that exists and misses one token must not read as finished work.

        The pre-run evaluation knows which clause fails; stating the path as merely
        outstanding throws that away, and a path failing one clause of five then
        reads exactly like a path that does not exist. Production evidence
        2026-08-21: attempt-4e473cc679af was handed `App.tsx`, which existed,
        exceeded its size floor, held two of its three required tokens and was
        reachable - and missed `Routes`. The executor read the file, found the
        contract substantially met, and spent the whole run repairing unrelated
        escape sequences in two other measured files.
        """
        (self.root / "frontend" / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend" / "src" / "App.tsx").write_text(
            "import { Sidebar } from './Sidebar';\nimport { Topbar } from './Topbar';\n" + "// shell\n" * 200,
            encoding="utf-8",
        )
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "navigation", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/App.tsx", "contains": ["Routes", "Sidebar", "Topbar"]}},
            {"criterion_id": "surface", "evaluator": {"type": "deliverable_surface", "path": "frontend/src/App.tsx", "min_chars": 1200, "required_any": ["route"], "require_reachable": False}},
        ])
        line = next(
            item for item in ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
            if item.startswith("- frontend/src/App.tsx")
        )
        self.assertIn("does not contain Routes", line, line)
        self.assertIn("contains none of route", line, line)
        self.assertNotIn("Sidebar;", line, "A clause that passes is not a shortfall.")
        self.assertNotIn("characters, not 1200", line, "The file clears its size floor.")
        self.assertNotIn("already satisfied", line)

    async def test_a_single_unsatisfied_deliverable_is_stated_as_work_not_only_listed(self):
        """The one contract shape where the imperative is the whole instruction.

        Defect #50 gave this same production contract a clause-level pre-run reading, so
        the listing stopped implying the file was fine. It stayed a listing. Gated on
        there being some already-satisfied path, the line that says what to spend the
        run on was withheld from every contract that had achieved nothing yet - and a
        contract measuring one path that fails is precisely that shape, so its objective
        went unstated in the only run where it was 100% of the work.

        What was left was a prompt whose sole imperative sentence was the boundary that
        closed it. attempt-0424a80f0a3f read App.tsx at its eighth tool call, wrote
        neither `Routes` nor `route` anywhere across 143 output chunks, edited one CSS
        file, and reported the shell complete with every gate green. The boundary was
        obeyed exactly; nothing else had been asked.
        """
        (self.root / "frontend" / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend" / "src" / "App.tsx").write_text(
            "import { Sidebar } from './Sidebar';\nimport { Topbar } from './Topbar';\n"
            + "// shell\n" * 200,
            encoding="utf-8",
        )
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "scope", "evaluator": {"type": "changed_files_subset", "paths": ["frontend/src/App.tsx", "frontend/src/styles.css"]}},
            {"criterion_id": "navigation", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/App.tsx", "contains": ["Routes", "Sidebar", "Topbar"]}},
            {"criterion_id": "surface", "evaluator": {"type": "deliverable_surface", "path": "frontend/src/App.tsx", "min_chars": 1200, "required_any": ["route"], "require_reachable": False}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        focus = next((item for item in lines if item.startswith("Spend this run on:")), None)
        self.assertIsNotNone(focus, "A contract with nothing satisfied still has to say what the run is for.")
        self.assertIn("frontend/src/App.tsx", focus)
        self.assertNotIn("already satisfied", focus, "Nothing passes, so the line claims nothing does.")

        boundary = next(item for item in lines if item.startswith("Do not modify anything outside:"))
        self.assertLess(lines.index(focus), lines.index(boundary),
                        "The obligation is stated before the boundary, not left to trail it.")

    async def test_absent_deliverable_carries_no_clause_detail(self):
        """A path that does not exist yet is already stated as work by the listing.

        Annotating it would restate the obligation the line above it carries, and the
        evaluator never read the file, so there is no clause reading to report.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "missing", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/Nowhere.tsx", "contains": ["Routes"]}},
        ])
        line = next(
            item for item in ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
            if item.startswith("- frontend/src/Nowhere.tsx")
        )
        self.assertNotIn("fails now", line, line)
        self.assertIn("must contain Routes", line, line)

    async def test_all_of_reports_only_the_checks_that_actually_fail(self):
        """One failing check must not smear its failure across the ones that pass.

        `all_of` fails as a whole, so every path it names goes into the outstanding
        set together. Production evidence 2026-08-21: task-681fa762d93f measured
        `requireRole` in three route files, `products.ts` already had it, and the
        contract stated all three identically - so the run could not tell which two
        files were the job.
        """
        (self.root / "backend" / "src" / "routes").mkdir(parents=True, exist_ok=True)
        for name, body in [("customers.ts", "export const list = 1;"), ("products.ts", "requireRole('ADMIN');"), ("orders.ts", "export const create = 1;")]:
            (self.root / "backend" / "src" / "routes" / name).write_text(body, encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "guards", "evaluator": {"type": "all_of", "checks": [
                {"type": "path_exists_contains", "path": "backend/src/routes/customers.ts", "contains": ["requireRole"]},
                {"type": "path_exists_contains", "path": "backend/src/routes/products.ts", "contains": ["requireRole"]},
                {"type": "path_exists_contains", "path": "backend/src/routes/orders.ts", "contains": ["requireRole"]},
            ]}},
        ])
        lines = {
            item.split(" ")[1]: item
            for item in ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
            if item.startswith("- backend/")
        }
        self.assertIn("does not contain requireRole", lines["backend/src/routes/customers.ts"])
        self.assertIn("does not contain requireRole", lines["backend/src/routes/orders.ts"])
        self.assertNotIn("fails now", lines["backend/src/routes/products.ts"], "This check passes; only its siblings are outstanding.")

    async def test_all_of_focus_line_excludes_the_sibling_check_that_passes(self):
        """The run-focus directive must name the work, not the whole criterion.

        Defect #50 stopped the annotation from smearing; the sets behind
        "(already satisfied)" and "Spend this run on:" still keyed on the criterion,
        so task-681fa762d93f told attempt-de1e80d8d515 to spend the run on
        `products.ts` as well - a file that had carried its role gate since the
        previous attempt. A third of a stated focus being already-passing work is
        indistinguishable, from the executor's side, from the paths that need it.
        """
        (self.root / "backend" / "src" / "routes").mkdir(parents=True, exist_ok=True)
        for name, body in [("customers.ts", "export const list = 1;"), ("products.ts", "requireRole('ADMIN');"), ("orders.ts", "export const create = 1;")]:
            (self.root / "backend" / "src" / "routes" / name).write_text(body, encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "guards", "evaluator": {"type": "all_of", "checks": [
                {"type": "path_exists_contains", "path": "backend/src/routes/customers.ts", "contains": ["requireRole"]},
                {"type": "path_exists_contains", "path": "backend/src/routes/products.ts", "contains": ["requireRole"]},
                {"type": "path_exists_contains", "path": "backend/src/routes/orders.ts", "contains": ["requireRole"]},
            ]}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        listing = {item.split(" ")[1]: item for item in lines if item.startswith("- backend/")}
        self.assertIn("already satisfied", listing["backend/src/routes/products.ts"])
        self.assertNotIn("already satisfied", listing["backend/src/routes/customers.ts"])
        self.assertNotIn("already satisfied", listing["backend/src/routes/orders.ts"])
        spend = next(item for item in lines if "Spend this run on:" in item).split("Spend this run on:")[1]
        self.assertIn("customers.ts", spend)
        self.assertIn("orders.ts", spend)
        self.assertNotIn("products.ts", spend, "This nested check passes; the run has no work there.")

    async def test_all_of_path_shared_with_a_failing_sibling_stays_outstanding(self):
        """One path, two clauses, one failing: the path is not satisfied.

        Per-check attribution must not let a passing check clear a path another
        check in the same `all_of` still fails, which would mark the file done while
        a clause it carries is unmet.
        """
        (self.root / "backend" / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "backend" / "src" / "app.ts").write_text("usersRouter", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "wiring", "evaluator": {"type": "all_of", "checks": [
                {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["usersRouter"]},
                {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["/api/users"]},
            ]}},
        ])
        lines = ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
        entry = next(item for item in lines if item.startswith("- backend/src/app.ts"))
        self.assertNotIn("already satisfied", entry, entry)
        self.assertIn("does not contain /api/users", entry, entry)
        # Nothing passes, so there is no mixed focus line to draw (defect #47's
        # shape) - what matters is that no part of the prompt reports the file done.
        self.assertNotIn("already satisfied", ProjectDispatcherService(None)._prompt(task, str(self.root)))

    async def test_shortfall_states_the_size_a_stub_falls_short_of(self):
        """A re-export shim satisfies nothing, and the contract should say so.

        `CustomersPage.tsx` was a 57-character re-export of another page. Stated only
        as outstanding it looks like a file needing a token added; stated with its
        length against the floor it is plainly a screen that was never written.
        """
        (self.root / "frontend" / "src" / "pages").mkdir(parents=True, exist_ok=True)
        (self.root / "frontend" / "src" / "pages" / "CustomersPage.tsx").write_text(
            'export { default } from "./CustomerPage";\n', encoding="utf-8",
        )
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "screen", "evaluator": {"type": "deliverable_surface", "path": "frontend/src/pages/CustomersPage.tsx", "min_chars": 1500, "required_any": ["/api/customers"], "require_reachable": False}},
        ])
        line = next(
            item for item in ProjectDispatcherService(None)._prompt(task, str(self.root)).splitlines()
            if item.startswith("- frontend/src/pages/CustomersPage.tsx")
        )
        self.assertIn("characters, not 1500", line, line)
        self.assertIn("contains none of /api/customers", line, line)

    async def test_forbidden_path_still_present_is_reported_as_a_shortfall(self):
        """A removal keeps its own rendering: it is not a deliverable with clauses.

        `path_absent` paths are boundaries, so they carry no clause annotation - the
        run-focus line names them as removals instead, which is the shape defect #43
        added and #47 widened.
        """
        (self.root / "debug-db.js").write_text("// scratch", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debug-db.js"}]}},
        ])
        prompt = ProjectDispatcherService(None)._prompt(task, str(self.root))
        self.assertNotIn("fails now", prompt, prompt)
        self.assertIn("removing debug-db.js", prompt)

    async def test_scope_and_absence_paths_are_never_reported_as_satisfied(self):
        """Boundaries are not deliverables, so they never carry a state marker.

        `changed_files_subset` cannot be judged before the run has changed
        anything, and a `path_absent` clause passes precisely because the path is
        missing - marking either as satisfied work would be a false reading.
        """
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        task.acceptance_json = json.dumps([
            {"criterion_id": "scope", "evaluator": {"type": "changed_files_subset", "paths": ["frontend/src/App.tsx"]}},
            {"criterion_id": "clean", "evaluator": {"type": "all_of", "checks": [{"type": "path_absent", "path": "debug-db.js"}]}},
        ])
        service = ProjectDispatcherService(None)
        self.assertEqual(service._satisfied_paths(task, str(self.root)), set())

    async def test_attempt_route_identity_is_the_registrys_own_name_for_the_route(self):
        """The identity comes from the record, so a name holding a slash survives it.

        Rebuilding the name from its parts put the provider prefix back only when the
        bare model name contained no slash - and NVIDIA namespaces its model names.
        Production evidence 2026-08-21: eleven consecutive dispatches were sent to
        `abacusai/dracarys-llama-3.1-70b-instruct`, a provider OpenCode does not have,
        because the `nvidia/` the registry holds the route under was dropped.
        """
        service = ProjectDispatcherService(None)
        self.assertEqual(service._route_identity({"provider": "fixture", "model": "coder", "model_id": "fixture/coder"}), "fixture/coder")
        self.assertEqual(
            service._route_identity({"provider": "nvidia", "model": "abacusai/dracarys-llama-3.1-70b-instruct", "model_id": "nvidia/abacusai/dracarys-llama-3.1-70b-instruct"}),
            "nvidia/abacusai/dracarys-llama-3.1-70b-instruct",
        )
        # A decision that predates `model_id` keeps the behaviour it always had.
        self.assertEqual(service._route_identity({"provider": "fixture", "model": "coder"}), "fixture/coder")
        self.assertIsNone(service._route_identity({"provider": None, "model": None}))

    async def test_a_namespaced_route_is_dispatched_and_held_under_its_real_identity(self):
        """One route, one name: what the CLI is asked for is what the hold is written against.

        Production evidence 2026-08-21, `_loop6`: eleven consecutive NEXA dispatches
        each spent their single probe on `abacusai/dracarys-llama-3.1-70b-instruct`
        and each returned `executor_local_failure`, a non-measurement the route never
        earned - the real route is `nvidia/abacusai/dracarys-llama-3.1-70b-instruct`
        and the name dispatched named no provider at all. The availability hold that
        should have withdrawn it after the first probe was refused, because no model
        record answers to the invented name, and the refusal was swallowed - so the
        route was re-probed every dispatch while the rest of the fleet went unmeasured.
        """
        namespaced_id = f"nvidia-fixture-{uuid.uuid4().hex[:8]}/abacusai/dracarys-llama-3.1-70b-instruct"
        provider, _, bare_model = namespaced_id.partition("/")
        self.assertIn("/", bare_model, "The point of the fixture is a model name that itself holds a slash.")
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=namespaced_id, name="Dracarys", provider=provider, category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=__import__("datetime").datetime.utcnow(), availability_expires_at=__import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(minutes=5)))
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.executor_needs_json = json.dumps({"capabilities": ["coding"], "certification_model_id": namespaced_id})
            agent = await session.get(AgentRecord, self.agent_id)
            agent.cli_command = "ai-fleet-executable-that-does-not-exist-4417"
            agent.detected_path = "ai-fleet-executable-that-does-not-exist-4417"
            agent.invocation_args = json.dumps([])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        try:
            # The hold under test is refused when the host is short of memory, and this
            # one is about the identity it is written against. See `_calm_host`.
            with _calm_host():
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
            self.assertEqual(response.status_code, 200, response.text)
            dispatched = response.json()["dispatched"][0]
            async with AsyncSessionLocal() as session:
                attempt = await session.get(RunAttemptRecord, dispatched["attempt_id"])
                attempt_model_id = attempt.model_id
                held = await session.get(ModelRecord, namespaced_id)
                availability_state = held.availability_state
                availability_ttl = (held.availability_expires_at - held.availability_checked_at).total_seconds()
                phantom = await session.get(ModelRecord, bare_model)
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(ModelRecord).where(ModelRecord.id == namespaced_id))
                await session.commit()
        receipt = dispatched["receipt"]
        self.assertEqual(receipt["measurement"]["classification"], "executor_local_failure")
        self.assertFalse(receipt["measurement"]["measured"])
        self.assertEqual(attempt_model_id, namespaced_id, "The attempt belongs to the route that ran, not to a name assembled from its parts.")
        self.assertEqual(receipt["invocation"]["model_argument"], namespaced_id, "The executor has to be asked for a route that exists.")
        self.assertIsNone(phantom, "Nothing may be recorded under the bare model name.")
        self.assertEqual(receipt["availability_hold"]["held"], True, "A non-measured route that cannot be held is re-probed forever.")
        self.assertEqual(receipt["availability_hold"]["model_id"], namespaced_id)
        self.assertEqual(availability_state, "unavailable")
        self.assertEqual(availability_ttl, NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS["executor_local_failure"])

    async def test_a_run_that_executed_the_route_renews_its_executable_availability(self):
        """The attempt that just used the route is an observation of the route.

        Executable availability was granted in one place only - the staged tournament
        promoting a route past the certification floor - and it expires. Production
        evidence 2026-08-21: `openai/gpt-5.4` was certified at 01:11:33 by tournament
        `47e141465271`, dispatched onto NEXA immediately as `run-6da28fdf1757` for 347
        seconds and 2.08M tokens of real file writes, and went unavailable at 01:41:33
        with its capability evidence still valid for another half hour. At 02:00:32 the
        next dispatch had no available route, spent its single probe exploring
        `aliyun/qwen3-max-2025-09-23`, which the provider refused for a spent
        allowance, and raised `execution_unavailable` - about a fleet whose newest
        execution evidence was six minutes of that route working.

        The renewal is availability only. This attempt misses its acceptance contract
        on purpose, and it changes no file: nothing about what the route can do may be
        inferred from disappointment (defects #9 and #11), and an empty diff carries no
        positive proof either, so no capability evidence may move in either direction.
        What a route that did write the workspace proves is defect #44's subject.
        """
        datetime_module = __import__("datetime")
        expiring = datetime_module.datetime.utcnow() + datetime_module.timedelta(seconds=60)
        async with AsyncSessionLocal() as session:
            model = await session.get(ModelRecord, self.model_id)
            model.availability_expires_at = expiring
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps([
                "-c",
                "import json;print(json.dumps({'type': 'text', 'part': {'id': 'prt_fixture'}, 'text': 'looked at the workspace'}));"
                "print(json.dumps({'type': 'step_finish', 'part': {'id': 'stp_fixture'}, 'tokens': {'input': 120, 'output': 40, 'total': 160}}))",
            ])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([{"criterion_id": "unwritten", "evaluator": {"type": "path_exists_contains", "path": "never-written.txt", "contains": ["absent"]}}])
            await session.commit()
            before = sorted((await session.execute(select(ModelCapabilityEvidenceRecord.id).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))).scalars().all())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        receipt = dispatched["receipt"]
        async with AsyncSessionLocal() as session:
            model = await session.get(ModelRecord, self.model_id)
            state, checked_at, expires_at = model.availability_state, model.availability_checked_at, model.availability_expires_at
            evidence = json.loads(model.availability_evidence)
            after = sorted((await session.execute(select(ModelCapabilityEvidenceRecord.id).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))).scalars().all())
        self.assertEqual(receipt["measurement"]["classification"], "model_executed")
        self.assertFalse(receipt["all_acceptance_satisfied"], "The point of the fixture is a route that ran and still missed the contract.")
        self.assertTrue(receipt["availability_renewal"]["renewed"], "The run that used the route is what says the route is usable.")
        self.assertEqual(receipt["availability_renewal"]["reason"], "model_produced_work")
        self.assertEqual(receipt["availability_renewal"]["model_id"], self.model_id)
        self.assertFalse(receipt["availability_hold"]["held"], "The hold and the renewal read the same classification and cannot both fire.")
        self.assertEqual(state, "available")
        self.assertEqual((expires_at - checked_at).total_seconds(), float(executable_availability_ttl_seconds()))
        self.assertGreater(expires_at, expiring, "A lapsing route that just did real work must not be left to lapse.")
        self.assertEqual(evidence["source"], "runtime", "Not the tournament: this observation came from production work.")
        self.assertEqual((evidence["run_id"], evidence["attempt_id"]), (dispatched["run_id"], dispatched["attempt_id"]), "The observation names the run that made it.")
        self.assertEqual(evidence["classification"], "model_executed")
        self.assertEqual(evidence["capability_scope"], "availability_only")
        self.assertIn("text", evidence["execution_proof"])
        self.assertEqual(evidence["tokens_reported"], 160)
        self.assertEqual(after, before, "This attempt changed no file, so it demonstrates nothing: an empty diff is neither capability nor incapacity.")

    async def test_a_run_that_wrote_the_workspace_renews_the_capability_floor(self):
        """The floor expires on the probe's clock; the work is what should renew it.

        Selection gates on availability and on current evidence that the route meets
        the coding floor. Defect #41 taught the first to be renewed by the production
        attempt that ran the route and left the second to the tournament, whose evidence
        lives an hour. Production evidence 2026-08-21: `openai/gpt-5.4` was certified at
        02:26:14 and lapsed at 03:26:14 in the middle of `attempt-9f20aee6a59d`, which
        ran 13 steps and 38 tool calls and left `ActivityPage.tsx` modified. Its
        availability was renewed to 03:56:56; the dispatch four seconds later dropped
        the route for want of capability evidence, spent its one renewal probe on the
        lapsed `aliyun/qwen3-max-2025-09-23` - refused for a spent allowance - and
        raised `execution_unavailable` with five tasks queued behind it.

        A lapse is the fleet not knowing, not the route being unable, and the answer was
        on disk in the workspace this attempt had just changed. This fixture holds that
        gate from the other side: a route whose `coding` evidence has lapsed is not
        selectable at all, so expiring the floor outright leaves nothing to dispatch and
        no renewal to observe. Here the floor is incomplete instead - setUp certifies the
        task's own `coding` need and nothing else - and what the run renews is the part
        the fleet cannot vouch for. The stall and its recovery are asserted directly in
        `test_capability_renewal_records_only_what_the_attempt_proved`, which expires the
        whole floor because it calls the renewal without needing a dispatch.
        """
        datetime_module = __import__("datetime")
        (self.root / "existing.txt").write_text("before", encoding="utf-8")
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps([
                "-c",
                "import json;"
                "open('existing.txt', 'w').write('after');"
                "open('created.txt', 'w').write('new');"
                "print(json.dumps({'type': 'tool_use', 'part': {'id': 'prt_fixture'}}));"
                "print(json.dumps({'type': 'step_finish', 'part': {'id': 'stp_fixture'}, 'tokens': {'input': 10, 'output': 5, 'total': 15}}))",
            ])
            await session.commit()
            service = ProjectDispatcherService(None)
            certified_before, evidence_before = await service.capabilities.satisfies(session, self.model_id, REVERIFY_CAPABILITIES)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()["dispatched"][0]["receipt"]
        async with AsyncSessionLocal() as session:
            service = ProjectDispatcherService(None)
            certified_after, evidence_after = await service.capabilities.satisfies(session, self.model_id, REVERIFY_CAPABILITIES)
            rows = (await session.execute(select(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))).scalars().all()
            written = {row.capability: row for row in rows if json.loads(row.evidence or "{}").get("probe") == "production_workspace_effect"}
        self.assertEqual(receipt["measurement"]["classification"], "model_executed")
        self.assertEqual(sorted(entry["change"] for entry in receipt["workspace_diff"]), ["added", "modified"])
        self.assertEqual(receipt["capability_renewal"]["renewed"], ["coding", "file_read", "file_write"], "A modified file is read and written; an added one is authored.")
        self.assertEqual(receipt["capability_renewal"]["reason"], "production_workspace_effect")
        self.assertEqual(receipt["capability_renewal"]["model_id"], self.model_id)
        self.assertEqual(sorted(written), ["coding", "file_read", "file_write"])
        for capability, row in written.items():
            self.assertTrue(row.supported, capability)
            self.assertEqual(row.provenance, "execution_measured")
            self.assertGreater(row.expires_at, datetime_module.datetime.utcnow())
            evidence = json.loads(row.evidence)
            self.assertEqual(evidence["classification"], "model_executed")
            self.assertEqual(evidence["changes_observed"], ["added", "modified"])
            self.assertTrue(evidence["positive_only"])
        self.assertFalse(certified_before, "The fixture starts where the fleet stalled: an incomplete floor under a route that works.")
        self.assertEqual(evidence_before["missing"], ["file_read", "file_write"], "The task needs `coding` and that is all the fixture certifies, so a re-verification of the floor is not current.")
        self.assertTrue(certified_after, "The work the route just did is the measurement, and it is newer than any probe.")
        self.assertEqual(evidence_after["missing"], [], "Nothing is left for a probe to buy: this attempt proved the whole floor on disk.")

    async def test_capability_renewal_records_only_what_the_attempt_proved(self):
        """Positive only, and only from filesystem effect the receipt carries.

        Renewing the floor from production must not become a back door for the
        inference defects #9, #11 and #29 closed: nothing here may write a negative
        observation, and a non-measurement or an empty diff must write nothing at all.
        What is claimed is read off the diff - a change is a write, an added or
        modified path is authored content, and a modified path was read before it was
        rewritten - so a proof the attempt does not carry is left to the probe.

        The fixture opens where the fleet stalled, with the floor expired under a route
        whose availability is current, so `_queue_already_served` reads the queue as
        unserved and the dispatch buys a probe run rather than doing the work. Renewing
        from the edit is what ends that, and the recovery is asserted here because
        expiring the floor makes the route unselectable and nothing would dispatch.
        """
        datetime_module = __import__("datetime")
        service = ProjectDispatcherService(None)
        measured = {"classification": "model_executed", "measured": True, "capability_conclusion_admissible": True, "reason": "model_produced_work", "execution_proof": ["tool_use", "workspace_diff"]}
        local = {**measured, "classification": "executor_local_failure", "measured": False, "capability_conclusion_admissible": False, "reason": "executor_launch_failed"}
        refused = {**measured, "classification": "provider_refusal", "measured": False, "capability_conclusion_admissible": False, "reason": "provider_allowance_exhausted"}
        edited = [{"path": "src/app.ts", "before": "a", "after": "b", "change": "modified"}]
        authored = [{"path": "src/new.ts", "before": None, "after": "b", "change": "added"}]
        removed = [{"path": "debris.js", "before": "a", "after": None, "change": "deleted"}]

        async def capabilities_written(session):
            rows = (await session.execute(select(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))).scalars().all()
            return {(row.id, row.capability, bool(row.supported)) for row in rows if json.loads(row.evidence or "{}").get("probe") == "production_workspace_effect"}

        call = dict(run_id="run-fixture", attempt_id="attempt-fixture")
        async with AsyncSessionLocal() as session:
            for row in (await session.execute(select(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))).scalars().all():
                row.expires_at = datetime_module.datetime.utcnow() - datetime_module.timedelta(seconds=1)
            await session.commit()
            model = await session.get(ModelRecord, self.model_id)
            served_before = await service._queue_already_served(session, [model], [{"coding"}], set(), datetime_module.datetime.utcnow())
            not_measured = await service._renew_measured_capabilities(session, self.model_id, local, workspace_diff=edited, **call)
            not_served = await service._renew_measured_capabilities(session, self.model_id, refused, workspace_diff=edited, **call)
            no_effect = await service._renew_measured_capabilities(session, self.model_id, measured, workspace_diff=[], **call)
            nameless = await service._renew_measured_capabilities(session, None, measured, workspace_diff=edited, **call)
            silent = await capabilities_written(session)
            deletion = await service._renew_measured_capabilities(session, self.model_id, measured, workspace_diff=removed, **call)
            after_deletion = {capability for _, capability, _ in await capabilities_written(session)}
            creation = await service._renew_measured_capabilities(session, self.model_id, measured, workspace_diff=authored, **call)
            edit = await service._renew_measured_capabilities(session, self.model_id, measured, workspace_diff=edited, **call)
            served_after = await service._queue_already_served(session, [model], [{"coding"}], set(), datetime_module.datetime.utcnow())
            written = await capabilities_written(session)
            aggregate = await service.capabilities.evidence.aggregate(session, self.model_id, datetime_module.datetime.utcnow())
        self.assertEqual((not_measured["renewed"], not_measured["reason"]), ([], "route_was_not_measured"))
        self.assertEqual((not_served["renewed"], not_served["reason"]), ([], "route_was_not_measured"), "A refusal measures the account, so it says nothing about the route.")
        self.assertEqual((no_effect["renewed"], no_effect["reason"]), ([], "attempt_produced_no_filesystem_evidence"), "An empty diff is not incapacity, and it is not proof either.")
        self.assertEqual((nameless["renewed"], nameless["reason"]), ([], "route_has_no_identity"))
        self.assertEqual(silent, set(), "Every case above wrote nothing at all.")
        self.assertEqual((deletion["renewed"], after_deletion), (["file_write"], {"file_write"}), "Removing a file is a write and nothing more.")
        self.assertEqual(creation["renewed"], ["coding", "file_write"], "Authoring a new file proves no read.")
        self.assertEqual(edit["renewed"], ["coding", "file_read", "file_write"])
        self.assertTrue(all(supported for _, _, supported in written), "Production evidence may only ever be positive.")
        self.assertTrue(all(aggregate["resolved"][capability]["supported"] for capability in REVERIFY_CAPABILITIES))
        self.assertEqual(aggregate["conflicts"], [], "A positive-only renewal cannot disagree with the probe that preceded it.")
        self.assertFalse(served_before, "A lapsed floor under a working route is the state that spent a probe run on an allowance-exhausted one.")
        self.assertTrue(served_after, "So the next dispatch serves the queue instead of buying what the work already showed.")

    async def test_only_an_attempt_that_reached_the_model_renews_availability(self):
        """Renewal reads the same classification as the hold, so a non-measurement grants nothing.

        A launch that never resolved the provider, and a provider that refused the
        account, observed nothing about whether the route can be executed. Renewing on
        either would restore exactly the routes the fleet has to stop dispatching to -
        the 02:00 dispatch spent its probe on an allowance-exhausted route as it was.
        """
        measured = {"classification": "model_executed", "measured": True, "reason": "model_produced_work", "execution_proof": ["text"], "tokens_reported": 160, "error_events": []}
        local = {**measured, "classification": "executor_local_failure", "measured": False, "reason": "executor_launch_failed", "execution_proof": [], "tokens_reported": 0}
        refused = {**measured, "classification": "provider_refusal", "measured": False, "reason": "provider_allowance_exhausted"}
        datetime_module = __import__("datetime")
        lapsed = datetime_module.datetime.utcnow() - datetime_module.timedelta(seconds=60)
        service = ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            model = await session.get(ModelRecord, self.model_id)
            model.availability_expires_at = lapsed
            await session.commit()
            now = datetime_module.datetime.utcnow()
            served_before = await service._queue_already_served(session, [model], [{"coding"}], set(), now)
            not_measured = await service._renew_measured_route(session, self.model_id, local, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            not_served = await service._renew_measured_route(session, self.model_id, refused, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            await session.refresh(model)
            still_lapsed = model.availability_expires_at
            nameless = await service._renew_measured_route(session, None, measured, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            missing = await service._renew_measured_route(session, f"absent-provider/absent-model-{uuid.uuid4().hex[:8]}", measured, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            renewed = await service._renew_measured_route(session, self.model_id, measured, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            model = await session.get(ModelRecord, self.model_id)
            renewed_expiry = model.availability_expires_at
            served_after = await service._queue_already_served(session, [model], [{"coding"}], set(), datetime_module.datetime.utcnow())
        self.assertEqual((not_measured["renewed"], not_measured["reason"]), (False, "route_was_not_measured"))
        self.assertEqual((not_served["renewed"], not_served["reason"]), (False, "route_was_not_measured"))
        self.assertEqual(still_lapsed, lapsed, "A non-measurement leaves the observation exactly as it found it.")
        self.assertEqual((nameless["renewed"], nameless["reason"]), (False, "route_has_no_identity"))
        self.assertEqual((missing["renewed"], missing["reason"], missing["error_code"]), (False, "no_model_record_for_route", "resource_not_found"))
        self.assertTrue(renewed["renewed"])
        self.assertEqual(renewed["ttl_seconds"], executable_availability_ttl_seconds())
        self.assertGreater(renewed_expiry, datetime_module.datetime.utcnow())
        self.assertFalse(served_before, "The fixture starts where the fleet stalled: proven capability, lapsed availability.")
        self.assertTrue(served_after, "So the next dispatch serves the queue instead of buying a probe run for what it already knows.")

    async def test_renewal_never_shortens_an_observation_that_already_outlasts_it(self):
        """Proving a route again may not make the fleet know it for less time."""
        datetime_module = __import__("datetime")
        measured = {"classification": "model_executed", "measured": True, "reason": "model_produced_work", "execution_proof": ["text"], "tokens_reported": 160}
        longer = datetime_module.datetime.utcnow() + datetime_module.timedelta(seconds=executable_availability_ttl_seconds() * 4)
        service = ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            model = await session.get(ModelRecord, self.model_id)
            model.availability_state = "available"
            model.availability_expires_at = longer
            await session.commit()
            outcome = await service._renew_measured_route(session, self.model_id, measured, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            model = await session.get(ModelRecord, self.model_id)
            await session.refresh(model)
            unchanged = model.availability_expires_at
        self.assertEqual((outcome["renewed"], outcome["reason"]), (False, "current_observation_outlasts_this_one"))
        self.assertEqual(unchanged, longer)

    async def test_a_hold_that_cannot_be_written_says_so_instead_of_passing_silently(self):
        """An unholdable route is re-probed next dispatch, so the receipt has to admit it.

        The swallowed `resource_not_found` is what let defect #37 run for eleven
        dispatches: every one of them reported a route withdrawn on a bounded TTL
        while nothing had been withdrawn at all.
        """
        measurement = {"classification": "executor_local_failure", "measured": False, "reason": "executor_launch_failed", "error_events": []}
        service = ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            missing = await service._hold_non_measured_route(session, f"absent-provider/absent-model-{uuid.uuid4().hex[:8]}", measurement, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            nameless = await service._hold_non_measured_route(session, None, measurement, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            measured = await service._hold_non_measured_route(session, self.model_id, {**measurement, "measured": True}, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            unheld_classification = await service._hold_non_measured_route(session, self.model_id, {**measurement, "classification": "model_executed"}, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            model = await session.get(ModelRecord, self.model_id)
            still_available = model.availability_state
        self.assertEqual((missing["held"], missing["reason"], missing["error_code"]), (False, "no_model_record_for_route", "resource_not_found"))
        self.assertEqual((nameless["held"], nameless["reason"]), (False, "route_has_no_identity"))
        self.assertEqual((measured["held"], measured["reason"]), (False, "route_was_measured"))
        self.assertEqual((unheld_classification["held"], unheld_classification["reason"]), (False, "classification_carries_no_hold"))
        self.assertEqual(still_available, "available", "Only a non-measurement withdraws a route, and only its own.")

    async def test_a_route_its_provider_says_is_gone_is_not_withheld_as_a_ten_minute_outage(self):
        """The hold the registry receives is the one the provider's answer justifies.

        Production evidence 2026-08-21: NVIDIA answered `410 Gone`, `The model
        'google/gemma-2-2b-it' has reached its end of life on 2026-07-27` and `404 Not
        Found` for route after route, and every one of them was held for the 600
        seconds sized to a provider that might answer in ten minutes - so a catalog of
        retired and non-chat routes re-entered the probe pool six times an hour,
        indefinitely, ahead of every provider whose credentials had never been tried.
        """
        retired = {
            "classification": "provider_unavailable",
            "measured": False,
            "reason": "provider_http_410",
            "error_events": [{"name": "APIError", "status_code": 410, "message": "Gone: The model has reached its end of life on 2026-07-27.", "ref": None}],
        }
        unserved = {**retired, "reason": "provider_http_404", "error_events": [{"name": "APIError", "status_code": 404, "message": "Not Found: 404 page not found", "ref": None}]}
        service = ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            gone = await service._hold_non_measured_route(session, self.model_id, retired, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            record = await session.get(ModelRecord, self.model_id)
            await session.refresh(record)
            gone_ttl = (record.availability_expires_at - record.availability_checked_at).total_seconds()
            gone_evidence = json.loads(record.availability_evidence)
            state_after_permanent_hold = record.availability_state
            not_found = await service._hold_non_measured_route(session, self.model_id, unserved, run_id="run-fixture", attempt_id="attempt-fixture", provider_propagation={})
            record = await session.get(ModelRecord, self.model_id)
            await session.refresh(record)
            unserved_ttl = (record.availability_expires_at - record.availability_checked_at).total_seconds()
        self.assertTrue(gone["held"])
        self.assertEqual(state_after_permanent_hold, "unavailable")
        self.assertEqual(gone["permanence"], "permanent")
        self.assertEqual(gone["permanence_basis"], "http_410_gone")
        self.assertEqual(gone["ttl_seconds"], MAX_AVAILABILITY_HOLD_SECONDS)
        self.assertEqual(gone_ttl, float(MAX_AVAILABILITY_HOLD_SECONDS), "The registry has to accept the hold the permanence asks for.")
        self.assertGreater(gone_ttl, NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS["provider_unavailable"] * 10)
        self.assertEqual(gone_evidence["permanence"], "permanent", "Why the hold is this long belongs with the observation that carries it.")
        self.assertEqual(gone_evidence["permanence_basis"], "http_410_gone")
        self.assertEqual(gone_evidence["classification"], "provider_unavailable")
        self.assertTrue(not_found["held"])
        self.assertEqual(not_found["permanence"], PERMANENCE_ROUTE_UNSERVED)
        self.assertEqual(unserved_ttl, float(PERMANENCE_HOLD_SECONDS[PERMANENCE_ROUTE_UNSERVED]))

    async def test_the_provider_due_a_probe_is_the_one_that_has_waited_longest(self):
        """One probe is spent per dispatch, so the rotation lives across dispatches or nowhere.

        Production evidence 2026-08-21: eleven consecutive NEXA dispatches went to
        `nvidia`, retiring one dead route apiece, while `openai`, `opencode`,
        `tokenrouter` and `zai` held thirty-five untried routes between them and were
        never reached once - `nvidia` sorts first by name, the order was recomputed from
        the fleet each dispatch, and nothing recorded that it had just had its turn.
        """
        import datetime as datetime_module
        now = datetime_module.datetime.utcnow()
        routes = ["aaa/m1", "aaa/m2", "mmm/m1", "mmm/m2", "zzz/only"]
        recency = {"aaa": now - datetime_module.timedelta(minutes=1), "mmm": now - datetime_module.timedelta(minutes=30)}

        def spend_five_probes(last_probed):
            """Pick the head, mark that provider as just probed, and pick again."""
            remaining, taken, clock = list(routes), [], now
            for _ in range(len(routes)):
                head = ProjectDispatcherService._provider_round_robin(remaining, last_probed)[0]
                taken.append(head.partition("/")[0])
                remaining.remove(head)
                clock += datetime_module.timedelta(seconds=1)
                if last_probed is not None:
                    last_probed[head.partition("/")[0]] = clock
            return taken

        self.assertEqual(spend_five_probes(dict(recency)), ["zzz", "mmm", "aaa", "mmm", "aaa"])
        # What the fleet did before the rotation carried across dispatches: two probes
        # into one provider before the second is tried once, and the untried credential
        # last of all.
        self.assertEqual(spend_five_probes(None), ["aaa", "aaa", "mmm", "mmm", "zzz"])
        # Providers waiting equally long keep the reproducible order they always had.
        self.assertEqual(
            ProjectDispatcherService._provider_round_robin(["big/m3", "big/m1", "big/m2", "big/m4", "small/only", "mid/b", "mid/a"], {}),
            ["big/m1", "mid/a", "small/only", "big/m2", "mid/b", "big/m3", "big/m4"],
        )

    async def test_a_provider_last_tried_is_read_from_what_the_fleet_actually_ran(self):
        """Any attempt spends the provider's turn, including one that never launched."""
        import datetime as datetime_module
        now = datetime_module.datetime.utcnow()
        suffix = uuid.uuid4().hex[:8]
        tried, untried = f"tried-{suffix}", f"untried-{suffix}"
        run_id = f"rotation-run-{suffix}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="rotation", project_id=self.project_id, status="failed"))
            session.add(RunAttemptRecord(id=f"rotation-old-{suffix}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=f"{tried}/coder", status="failed", outcome="launch_failed", started_at=now - datetime_module.timedelta(hours=2)))
            session.add(RunAttemptRecord(id=f"rotation-new-{suffix}", run_id=run_id, attempt_number=2, executor_type="agent", model_id=f"{tried}/writer", status="failed", outcome="non_zero_exit", started_at=now - datetime_module.timedelta(minutes=3)))
            await session.commit()
        async with AsyncSessionLocal() as session:
            recency = await ProjectDispatcherService(None)._provider_probe_recency(session)
        self.assertIn(tried, recency)
        self.assertNotIn(untried, recency, "A provider with no attempt has waited longest by definition.")
        self.assertLess((now - recency[tried]).total_seconds(), 600, "The provider's turn is when it was last tried, not when it was first tried.")
        ordered = ProjectDispatcherService._provider_round_robin([f"{tried}/coder", f"{tried}/writer", f"{untried}/coder"], recency)
        self.assertEqual(ordered[0], f"{untried}/coder", "The untried credential is the one a bounded probe learns something from.")

    async def test_the_cli_is_asked_for_the_full_route_name_including_a_namespaced_model(self):
        """The `--model` argument and the recorded identity come from the same source."""
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            argv = ProjectDispatcherService(None)._build_argv_with_model(
                _OpenCodeStandIn(agent), "prompt", str(self.root),
                {"provider": "nvidia", "model": "abacusai/dracarys-llama-3.1-70b-instruct", "model_id": "nvidia/abacusai/dracarys-llama-3.1-70b-instruct"},
            )
        self.assertEqual(argv[argv.index("--model") + 1], "nvidia/abacusai/dracarys-llama-3.1-70b-instruct")

    async def test_verified_discovered_route_precedes_unverified_bootstrap_routes(self):
        model_id = f"fixture-provider/coder-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=model_id, name="Fixture coder", provider="fixture-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=__import__("datetime").datetime.utcnow(), availability_expires_at=__import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(minutes=5)))
            await session.commit()
            await ExecutorCapabilityService().certify(session, model_id, {"coding": True}, {"run_id": "fixture"})
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._select_model(session, task)
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id))
            await session.delete(await session.get(ModelRecord, model_id))
            await session.commit()
        candidates = {(item["provider"], item["model"]): item for item in decision["candidate_routes"]}
        self.assertEqual(decision["availability"], "verified")
        self.assertEqual(candidates[("fixture-provider", model_id.split("/", 1)[1])]["availability"], "verified")

    async def test_current_zero_quota_excludes_verified_route(self):
        now = __import__("datetime").datetime.utcnow()
        model_id = f"quota-provider/coder-{uuid.uuid4().hex[:8]}"
        quota_id = f"quota-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=model_id, name="Quota coder", provider="quota-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=now + __import__("datetime").timedelta(minutes=5)))
            session.add(QuotaObservationRecord(id=quota_id, provider_instance_id="opencode:quota-provider", scope=model_id.split("/", 1)[1], unit="requests", remaining_value=0, source="measured", checked_at=now, expires_at=now + __import__("datetime").timedelta(minutes=5)))
            await session.commit()
            await ExecutorCapabilityService().certify(session, model_id, {"coding": True}, {"run_id": "fixture"})
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._select_model(session, task)
            candidates = {(item["provider"], item["model"]): item for item in decision["candidate_routes"]}
            await session.delete(await session.get(QuotaObservationRecord, quota_id))
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id))
            await session.delete(await session.get(ModelRecord, model_id))
            await session.commit()
        self.assertNotEqual((decision["provider"], decision["model"]), ("quota-provider", model_id.split("/", 1)[1]))
        self.assertTrue(candidates[("quota-provider", model_id.split("/", 1)[1])]["temporarily_unavailable"])

    async def test_repeated_recent_timeout_history_ranks_behind_fresh_route(self):
        now = __import__("datetime").datetime.utcnow()
        fresh_id = f"fresh-provider/coder-{uuid.uuid4().hex[:8]}"
        timed_id = f"timed-provider/coder-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            for model_id, provider in ((fresh_id, "fresh-provider"), (timed_id, "timed-provider")):
                session.add(ModelRecord(id=model_id, name=model_id, provider=provider, category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=now + __import__("datetime").timedelta(minutes=5)))
            for index in range(3):
                run_id = f"timeout-run-{uuid.uuid4().hex[:8]}"
                attempt_id = f"timeout-attempt-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="timeout", project_id=self.project_id, status="timed_out"))
                session.add(RunAttemptRecord(id=attempt_id, run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=timed_id, status="timed_out", outcome="timed_out", receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            await session.commit()
            await ExecutorCapabilityService().certify(session, fresh_id, {"coding": True}, {"run_id": "fresh"})
            await ExecutorCapabilityService().certify(session, timed_id, {"coding": True}, {"run_id": "timed"})
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)._select_model(session, task)
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == timed_id))
            await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "timeout"))
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id.in_([fresh_id, timed_id])))
            await session.execute(delete(ModelRecord).where(ModelRecord.id.in_([fresh_id, timed_id])))
            await session.commit()
        candidate_ids = [item["model_id"] for item in decision["candidate_routes"]]
        self.assertLess(candidate_ids.index(fresh_id), candidate_ids.index(timed_id))
        timed = next(item for item in decision["candidate_routes"] if item["model_id"] == timed_id)
        self.assertEqual(timed["recent_timeout_or_no_effect"], 3)

    async def test_satisfied_acceptance_completes_task_despite_non_zero_exit(self):
        """A route that wrote the accepted work then exited non-zero must not be discarded."""
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps([
                "-c",
                "open('proof.txt','w').write('accepted'); raise SystemExit(1)",
            ])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "proof", "description": "Proof file exists.", "evaluator": {"type": "paths_exist", "paths": ["proof.txt"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            run = await session.get(TaskRun, dispatched["run_id"])
            attempt = await session.get(RunAttemptRecord, dispatched["attempt_id"])
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
        self.assertTrue((self.root / "proof.txt").is_file())
        self.assertEqual(dispatched["receipt"]["completion_detection"]["reason"], "acceptance_satisfied")
        self.assertTrue(dispatched["all_acceptance_satisfied"])
        self.assertEqual(dispatched["status"], "completed")
        self.assertEqual(run.status, "completed")
        self.assertEqual(task.state, "completed")
        self.assertEqual(attempt.status, "completed")
        self.assertIsNone(attempt.error_code)
        self.assertEqual(negative, [], "A route that satisfied acceptance must not receive negative capability evidence.")

    async def test_unsatisfied_acceptance_still_fails_on_non_zero_exit(self):
        """A measured attempt that missed its contract fails the task.

        The attempt speaks before it exits, so the model demonstrably ran: the miss is
        a reading of the work, and `failed` is a statement about work that happened.
        """
        spoke_then_exited = 'import json; print(json.dumps({"type": "text", "part": {"text": "read the workspace and stopped"}})); raise SystemExit(1)'
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", spoke_then_exited])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "proof", "description": "Proof file exists.", "evaluator": {"type": "paths_exist", "paths": ["missing.txt"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
        self.assertFalse(dispatched["all_acceptance_satisfied"])
        self.assertTrue(dispatched["measurement"]["measured"], "The attempt spoke, so it measured the route and reached the work.")
        self.assertEqual(dispatched["status"], "failed")
        self.assertEqual(task.state, "failed")
        self.assertFalse(dispatched["receipt"]["task_disposition"]["requeued"])

    async def test_non_measured_attempt_returns_the_task_to_the_queue(self):
        """A process that produced no execution signal has not judged the task.

        attempt-0144bc5d1502: the executor CLI's own runtime aborted on
        `MemoryExhaustion` 31 seconds in - exit 0xC0000409, before one model step, no
        events, no tokens, no diff. TEMM read the route correctly and published no
        incapacity, then wrote `failed` on task-1036cd4d6fc2 and dropped it from the
        ready queue. Getting it back would have cost a repair generation from an anchor
        capped at three, so a host memory condition would have spent a budget that
        exists to bound repair recursion. The run keeps its failure and its
        diagnostics; the task keeps its place.
        """
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", "raise SystemExit(1)"])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "proof", "description": "Proof file exists.", "evaluator": {"type": "paths_exist", "paths": ["missing.txt"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            run = await session.get(TaskRun, dispatched["run_id"])
            attempt = await session.get(RunAttemptRecord, dispatched["attempt_id"])
        self.assertFalse(dispatched["measurement"]["measured"])
        self.assertFalse(dispatched["all_acceptance_satisfied"])
        self.assertEqual(task.state, "planned", "A task whose work was never reached belongs in the queue.")
        self.assertEqual(task.current_run_id, dispatched["run_id"], "The requeued task still points at the run that could not measure it.")
        self.assertEqual(dispatched["status"], "failed")
        self.assertEqual(run.status, "failed", "The run did fail, and its record must say so.")
        self.assertEqual(attempt.error_code, "non_zero_exit", "The diagnostics that classify the failure must survive the requeue.")
        self.assertTrue(dispatched["receipt"]["task_disposition"]["requeued"])
        self.assertEqual(dispatched["receipt"]["task_disposition"]["classification"], "no_execution_signal")

    async def test_productive_attempt_that_missed_acceptance_keeps_route_certified(self):
        """A route that wrote real files must stay dispatchable after missing acceptance.

        Acceptance names the artifact the contract wants; capability evidence records
        what the route can do. Deriving the second from the first published incapacity
        that the attempt's own diff contradicts, and because the newest execution
        measurement wins aggregation it left the dispatcher with no selectable route.
        """
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", "open('written.txt','w').write('real work')"])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "contracted", "description": "Contracted artifact exists.", "evaluator": {"type": "paths_exist", "paths": ["contracted.txt"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            certified, _ = await ExecutorCapabilityService().satisfies(session, self.model_id, {"coding"})
        self.assertTrue((self.root / "written.txt").is_file())
        self.assertFalse(dispatched["all_acceptance_satisfied"])
        self.assertTrue(dispatched["workspace_diff"])
        self.assertEqual(negative, [], "A measured file write must not be recorded as incapacity.")
        self.assertTrue(certified, "A route that wrote real files must stay dispatchable.")

    async def test_zero_effect_attempt_keeps_route_certified(self):
        """A route that ran cleanly and changed nothing has not proved it cannot code.

        An executor that inspects the workspace and declines to write - because it
        judges the requirement already met, or picks the wrong artifact - made a
        judgement. Publishing that as incapacity hard-gated the only certified route
        out of selection, so the next dispatch failed `execution_unavailable` rather
        than trying again or trying elsewhere. The no-effect signal belongs to the
        route-health penalties in `rank()`, which demote without deadlocking.
        """
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", "print('changed nothing')"])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "contracted", "description": "Contracted artifact exists.", "evaluator": {"type": "paths_exist", "paths": ["contracted.txt"]}},
            ])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            certified, _ = await ExecutorCapabilityService().satisfies(session, self.model_id, {"coding"})
        self.assertFalse(dispatched["workspace_diff"])
        self.assertFalse(dispatched["all_acceptance_satisfied"])
        self.assertEqual(negative, [], "Declining to write is not a measurement of incapacity.")
        self.assertTrue(certified, "A clean-exit attempt must leave the route dispatchable.")

    async def test_provider_refusal_holds_the_route_out_without_blaming_it(self):
        """A provider that refused to serve the request said nothing about the route.

        The CLI reports the refusal as an event and exits non-zero, which reads
        exactly like a route that tried the work and failed it. Two things follow
        from telling them apart, and neither happened: the refused route stayed
        eligible, so every later dispatch spent a full attempt earning the identical
        refusal, and the refusal counted against the route's health, so it kept
        carrying penalties for requests it was never given. Production evidence
        2026-08-19: attempt-e2cd417ed8aa spent 253s reaching HTTP 403
        `insufficient_quota` and was recorded as `non_zero_exit`.
        """
        now = __import__("datetime").datetime.utcnow()
        provider = self.model_id.split("/", 1)[0]
        spare_id = f"spare-provider/coder-{uuid.uuid4().hex[:8]}"
        refusal_event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": "Free quota exhausted. To continue accessing the model on a paid basis, please add funds.",
            "statusCode": 403,
            "responseBody": '{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}',
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Refusing provider", adapter_id="opencode"))
            # A second healthy route, so selection can still return one and the
            # assertions can name which route it chose instead of merely failing.
            session.add(ModelRecord(id=spare_id, name="Spare coder", provider="spare-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=now + __import__("datetime").timedelta(minutes=5)))
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({refusal_event!r}); raise SystemExit(1)"])
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.acceptance_json = json.dumps([
                {"criterion_id": "contracted", "description": "Contracted artifact exists.", "evaluator": {"type": "paths_exist", "paths": ["contracted.txt"]}},
            ])
            await session.commit()
            await ExecutorCapabilityService().certify(session, spare_id, {"coding": True}, {"run_id": "spare"})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        dispatcher = ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            attempt = await session.get(RunAttemptRecord, dispatched["attempt_id"])
            error_code = attempt.error_code
            observations = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ))).scalars().all()
            health = await dispatcher._route_health(session, self.project_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            await self._requeue(session, self.task_id)
            decision = await dispatcher._select_model(session, task)
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == spare_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == spare_id))
            await session.commit()
        refused = next(item for item in decision["candidate_routes"] if item["model_id"] == self.model_id)

        self.assertEqual(dispatched["receipt"]["provider_refusal"]["status_code"], 403)
        self.assertTrue(dispatched["receipt"]["provider_refusal"]["allowance_exhausted"])
        self.assertEqual(dispatched["receipt"]["completion_detection"]["reason"], "provider_refused")
        self.assertEqual(error_code, "provider_allowance_exhausted", "The exit code is not the cause; the refusal is.")
        # `*`, not the model: this provider refused the request by naming its own
        # account allowance, so that is the allowance the observation records.
        self.assertEqual([(item.scope, item.remaining_value) for item in observations], [("*", 0)])
        self.assertEqual(decision["model_id"], spare_id, "A refused route must not be dispatched again while the refusal stands.")
        self.assertTrue(refused["temporarily_unavailable"])
        self.assertEqual(health[self.model_id]["recent_failures"], 0, "A refusal is not the route's failure.")
        self.assertEqual(health[self.model_id]["failed"], 0)
        self.assertEqual(negative, [], "A refusal is no measurement of incapacity.")

    async def test_a_rate_refusal_reaches_the_ledger_whatever_words_it_arrives_in(self):
        """A 429 is a spent allowance whether or not its wording is one TEMM lists.

        Every durable consequence of a refusal - the observation `_is_exhausted`
        reads, the horizon that lengthens on repetition, the scope that decides how
        much is withheld - hangs off `allowance_exhausted`, and that flag was decided
        by matching the message against a phrase list. So a provider whose wording
        was not on the list left no record at all, and the fleet's memory of a spent
        allowance became a matter of its supplier's vocabulary.

        Production evidence 2026-08-21 12:22, attempt-ac22ecc832d8: `opencode:openai`
        answered 429 "The usage limit has been reached" - matching none of "quota",
        "rate limit", "too many requests", "credit" - on `gpt-5.4-fast`, the one route
        that had served NEXA all afternoon. No observation was written, no horizon
        derived, no scope recorded; the six dispatches that followed spent six probes
        on uncredentialed providers.
        """
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        provider, _, model_name = self.model_id.partition("/")
        refusal_event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": "The usage limit has been reached",
            "statusCode": 429,
            "responseBody": "{}",
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Rate-limited provider", adapter_id="opencode"))
            await session.commit()
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({refusal_event!r}); raise SystemExit(1)"])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            written = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ).order_by(QuotaObservationRecord.checked_at.desc()))).scalars().first()
            excluded = await ProjectDispatcherService(None)._exhausted_routes(session, datetime_module.datetime.utcnow())
        refusal = dispatched["receipt"]["provider_refusal"]

        self.assertTrue(refusal["allowance_exhausted"], "429 states the allowance is spent; no phrase has to say so.")
        self.assertEqual(refusal["status_code"], 429)
        self.assertEqual(refusal["refusal_scope"], "model", "Nothing named the account, so the narrower reading stands.")
        self.assertIsNotNone(written, "The refusal that used to be recorded nowhere is now in the ledger.")
        self.assertEqual(written.scope, model_name, "Recorded under the model the provider actually refused.")
        self.assertEqual(written.remaining_value, 0)
        self.assertEqual(refusal["withheld"], {"ttl_seconds": 3600, "basis": "first_look_at_this_allowance", "reconfirmations": 0}, "A first look earns the base hold, and the receipt says so.")
        self.assertEqual(written.id, refusal["quota_observation_id"])
        self.assertIn((f"opencode:{provider}", model_name), excluded, "Selection and the tournament both read this set; before the fix it was empty.")

    async def test_a_refusal_the_provider_never_dated_is_withheld_longer_each_time(self):
        """The hold on a spent allowance is derived from the looks already taken.

        A provider that names no reset time is guessed at, and the guess was reset to
        the same hour however often it had already been contradicted - so the fleet
        paid one probe an hour to re-learn a standing fact, and the queue behind that
        probe was answered `execution_unavailable`. Production evidence 2026-08-21:
        `opencode:aliyun` answered "Free quota exhausted ... please add funds" at
        23:33, 00:39, 02:00, 03:27 and 08:42, five looks and five one-hour holds, and
        at 08:42 every renewable route in the fleet belonged to that account, so five
        ready NEXA tasks waited on a horizon that could never lengthen.
        """
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        provider = self.model_id.split("/", 1)[0]
        spare_id = f"spare-provider/coder-{uuid.uuid4().hex[:8]}"
        refusal_event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": "Free quota exhausted. To continue accessing the model on a paid basis, please add funds.",
            "statusCode": 403,
            "responseBody": '{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}',
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Refusing provider", adapter_id="opencode"))
            session.add(ModelRecord(id=spare_id, name="Spare coder", provider="spare-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            await session.commit()
            await ExecutorCapabilityService().certify(session, spare_id, {"coding": True}, {"run_id": "spare"})
            # Two looks already taken and already lapsed: exactly the state a third
            # dispatch finds, and the state that used to buy a third identical hour.
            for hours in (3, 2):
                await ProjectDispatcherService(None).quota.record(session, f"opencode:{provider}", {
                    "scope": "*", "unit": "requests", "remaining": 0, "source": "measured",
                    "ttl_seconds": 3600, "checked_at": now - datetime_module.timedelta(hours=hours),
                    "evidence": {"reason": "provider_refusal"},
                })
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({refusal_event!r}); raise SystemExit(1)"])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            written = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ).order_by(QuotaObservationRecord.checked_at.desc()))).scalars().first()
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == spare_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == spare_id))
            await session.commit()
        withheld = dispatched["receipt"]["provider_refusal"]["withheld"]

        self.assertEqual(withheld["reconfirmations"], 2, "Two looks already found this allowance spent.")
        self.assertEqual(withheld["basis"], "reconfirmed_spent_allowance")
        self.assertEqual(withheld["ttl_seconds"], 14400)
        self.assertEqual((written.expires_at - written.checked_at).total_seconds(), 14400.0, "The hold the ledger writes is the hold the receipt states.")
        self.assertEqual(json.loads(written.evidence)["horizon"]["ttl_seconds"], 14400, "The observation carries why it is as long as it is.")
        self.assertEqual(written.remaining_value, 0)
        self.assertEqual(written.scope, "*")

    async def test_a_route_that_serves_again_corrects_the_ledgers_spent_claim(self):
        """A served request is the only measurement that can shorten a spent hold.

        The horizon lengthens on each reconfirmed refusal, which needs a way back
        down or an account topped up after its worst hour keeps that hour's hold for
        good. Serving a request produces no quota event of its own, so the run is the
        measurement: this attempt is a route the ledger's newest look says is spent,
        reached because that look had lapsed, doing real work.
        """
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        provider = self.model_id.split("/", 1)[0]
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Recovering provider", adapter_id="opencode"))
            await session.commit()
            await ProjectDispatcherService(None).quota.record(session, f"opencode:{provider}", {
                "scope": "*", "unit": "requests", "remaining": 0, "source": "measured",
                "ttl_seconds": 3600, "checked_at": now - datetime_module.timedelta(hours=2),
                "evidence": {"reason": "provider_refusal"},
            })
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps([
                "-c",
                "import json;print(json.dumps({'type': 'text', 'part': {'id': 'prt_fixture'}, 'text': 'served the request'}));"
                "print(json.dumps({'type': 'step_finish', 'part': {'id': 'stp_fixture'}, 'tokens': {'input': 90, 'output': 30, 'total': 120}}))",
            ])
            await session.commit()
            escalated = await ProjectDispatcherService(None).quota.refusal_horizon(session, f"opencode:{provider}", "*")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            newest = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ).order_by(QuotaObservationRecord.checked_at.desc()))).scalars().first()
            recovered = await ProjectDispatcherService(None).quota.refusal_horizon(session, f"opencode:{provider}", "*")
            excluded = await ProjectDispatcherService(None)._exhausted_routes(session, datetime_module.datetime.utcnow())

        self.assertEqual(dispatched["receipt"]["measurement"]["classification"], "model_executed")
        self.assertEqual(escalated["ttl_seconds"], 7200, "The lapsed look would have bought a longer hold had this route refused again.")
        self.assertEqual(json.loads(newest.evidence)["reason"], "provider_served_request", "The newest thing the ledger knows is that the provider served this request.")
        self.assertEqual(json.loads(newest.evidence)["attempt_id"], dispatched["attempt_id"], "The observation names the attempt that made it.")
        self.assertIsNone(newest.remaining_value, "A served request reveals that the allowance was not spent, not how much is left.")
        self.assertEqual((recovered["ttl_seconds"], recovered["reconfirmations"]), (3600, 0), "A refusal after a recovery is a first look, not a fifth.")
        self.assertNotIn((f"opencode:{provider}", "*"), excluded, "An observation claiming no number withholds nothing.")

    async def test_an_account_level_refusal_holds_out_the_providers_other_models_too(self):
        """The provider named its account's allowance, which every model on it shares.

        Recorded under the one model that happened to be dispatched, the fact has to
        be rediscovered once per model - and each rediscovery costs a full attempt
        the provider was never going to serve. Production evidence 2026-08-21:
        `opencode:aliyun` wrote thirteen model-scoped observations inside two
        minutes from one identical account-level message, each holding out one route
        of roughly eighty, while every NEXA dispatch in that window answered 409
        `execution_unavailable` and no task advanced.

        The exclusion must still stop at the provider: an account that is out of
        credit says nothing about anybody else's account, which is what the spare
        route on a second provider is here to prove.
        """
        now = __import__("datetime").datetime.utcnow()
        expires = now + __import__("datetime").timedelta(minutes=5)
        provider = self.model_id.split("/", 1)[0]
        sibling_id = f"{provider}/coder-sibling"
        spare_id = f"spare-provider/coder-{uuid.uuid4().hex[:8]}"
        event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": 'Free quota exhausted. To continue accessing the model on a paid basis, please add funds or disable the "use free tier only" mode in the management console.',
            "statusCode": 403,
            "responseBody": '{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}',
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Refusing provider", adapter_id="opencode"))
            session.add(ModelRecord(id=sibling_id, name="Sibling coder", provider=provider, category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=expires))
            session.add(ModelRecord(id=spare_id, name="Spare coder", provider="spare-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=expires))
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({event!r}); raise SystemExit(1)"])
            await session.commit()
            await ExecutorCapabilityService().certify(session, sibling_id, {"coding": True}, {"run_id": "sibling"})
            await ExecutorCapabilityService().certify(session, spare_id, {"coding": True}, {"run_id": "spare"})
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            before = await ProjectDispatcherService(None)._select_model(session, task)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        async with AsyncSessionLocal() as session:
            observations = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ))).scalars().all()
            await self._requeue(session, self.task_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await ProjectDispatcherService(None)._select_model(session, task)
            for stale in (sibling_id, spare_id):
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == stale))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == stale))
            await session.commit()
        held_out = {item["model_id"] for item in decision["candidate_routes"] if item.get("temporarily_unavailable")}

        self.assertIn(before["model_id"], {self.model_id, sibling_id}, "Both provider routes were dispatchable before the refusal.")
        self.assertEqual([(item.scope, item.remaining_value) for item in observations], [("*", 0)])
        self.assertEqual({self.model_id, sibling_id}, held_out, "One account's spent allowance covers every model on that account.")
        self.assertEqual(decision["model_id"], spare_id, "Another provider's account was never refused anything.")

    async def test_a_rejected_credential_holds_out_every_model_behind_it(self):
        """The provider rejected the key, and the key is not one model's.

        Production evidence 2026-08-21: thirteen consecutive dispatches probed
        thirteen different `amazon-bedrock` models and every one was answered HTTP
        403 "Authentication failed: Please make sure your API Key is valid." The
        message claims no allowance, so nothing reached the quota ledger, and a
        refusal is never recorded as incapacity, so nothing held the provider out
        either - leaving a hundred-odd bedrock routes each still queued to buy the
        same fact one dispatch at a time while no other provider was sampled.

        What must not happen instead is a quota claim: a rejected key has spent no
        allowance, and recording `remaining: 0` for it would restate exactly the
        falsehood that ledger was fixed to stop making. The provider instance is
        seeded here so that such a write would have succeeded had one been made.
        """
        now = __import__("datetime").datetime.utcnow()
        expires = now + __import__("datetime").timedelta(minutes=5)
        provider = self.model_id.split("/", 1)[0]
        sibling_id = f"{provider}/coder-sibling"
        spare_id = f"spare-provider/coder-{uuid.uuid4().hex[:8]}"
        event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": 'Forbidden: {"Message":"Authentication failed: Please make sure your API Key is valid."}',
            "statusCode": 403,
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Rejecting provider", adapter_id="opencode"))
            session.add(ModelRecord(id=sibling_id, name="Sibling coder", provider=provider, category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=expires))
            session.add(ModelRecord(id=spare_id, name="Spare coder", provider="spare-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=expires))
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({event!r}); raise SystemExit(1)"])
            await session.commit()
            await ExecutorCapabilityService().certify(session, sibling_id, {"coding": True}, {"run_id": "sibling"})
            await ExecutorCapabilityService().certify(session, spare_id, {"coding": True}, {"run_id": "spare"})
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            before = await ProjectDispatcherService(None)._select_model(session, task)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            attempt = await session.get(RunAttemptRecord, dispatched["attempt_id"])
            error_code = attempt.error_code
            observations = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ))).scalars().all()
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id.in_([self.model_id, sibling_id]),
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            await self._requeue(session, self.task_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await ProjectDispatcherService(None)._select_model(session, task)
            for stale in (sibling_id, spare_id):
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == stale))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == stale))
            await session.commit()
        held_out = {item["model_id"] for item in decision["candidate_routes"] if item.get("temporarily_unavailable")}

        self.assertIn(before["model_id"], {self.model_id, sibling_id}, "Both provider routes were dispatchable before the refusal.")
        self.assertEqual(dispatched["receipt"]["provider_refusal"]["refusal_kind"], "credential")
        self.assertEqual(dispatched["receipt"]["provider_refusal"]["refusal_scope"], "provider")
        self.assertEqual(error_code, "provider_credential_rejected", "The operator has a key to repair, not a task that failed.")
        self.assertEqual(observations, [], "A rejected key has spent no allowance, so it makes no quota claim.")
        self.assertEqual(negative, [], "A refused route demonstrated nothing, so it cannot be recorded as incapable.")
        self.assertEqual({self.model_id, sibling_id}, held_out, "One rejected key covers every model behind it.")
        self.assertEqual(decision["model_id"], spare_id, "Another provider's credential was never rejected.")

    async def test_a_provider_that_has_served_anything_since_is_not_refusing_the_account(self):
        """The provider-wide reading holds only while the provider's newest word is a refusal.

        Widening from each route's own newest attempt would let one stale refusal
        withdraw a provider that is demonstrably serving requests - so the widening
        is read from the provider's newest attempt, and a served attempt after it
        ends the hold with nothing reset by hand. The route that was itself refused
        keeps its own bound, which is the narrow fact still standing.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        dispatcher = dispatcher_module.ProjectDispatcherService(None)
        provider = f"credential-window-{uuid.uuid4().hex[:8]}"
        refused_id, served_id = f"{provider}/coder-a", f"{provider}/coder-b"
        run_id = f"credential-window-run-{uuid.uuid4().hex[:8]}"
        served_attempt_id = f"credential-window-served-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="credential-window", project_id=self.project_id, status="failed"))
            session.add(RunAttemptRecord(id=f"credential-window-refused-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=refused_id, status="failed", outcome="non_zero_exit", error_code="provider_credential_rejected", started_at=now - datetime_module.timedelta(minutes=20), completed_at=now - datetime_module.timedelta(minutes=20), receipt_json=json.dumps({"provider_refusal": {"status_code": 403, "allowance_exhausted": False, "refusal_scope": "provider", "refusal_kind": "credential"}})))
            # Newer, and served: whatever the provider said about the key, it is
            # accepting it now.
            session.add(RunAttemptRecord(id=served_attempt_id, run_id=run_id, attempt_number=2, executor_type="agent", model_id=served_id, status="failed", outcome="non_zero_exit", error_code="acceptance_unsatisfied", started_at=now - datetime_module.timedelta(minutes=5), completed_at=now - datetime_module.timedelta(minutes=5), receipt_json=json.dumps({"duration_ms": 40000})))
            await session.commit()
        try:
            async with AsyncSessionLocal() as session:
                window = now - datetime_module.timedelta(hours=1)
                with_service = await dispatcher._recent_refusals(session, window)
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.id == served_attempt_id))
                await session.commit()
                without_service = await dispatcher._recent_refusals(session, window)
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id))
                await session.execute(delete(TaskRun).where(TaskRun.id == run_id))
                await session.commit()

        self.assertFalse(dispatcher._is_refused(with_service, served_id), "A route the provider served is not being refused.")
        self.assertTrue(dispatcher._is_refused(with_service, refused_id), "The refusal on this route's own newest attempt still stands.")
        self.assertTrue(dispatcher._is_refused(without_service, served_id), "With the refusal newest, the whole provider is held out.")
        self.assertIn(f"{provider}/*", without_service)

    async def test_a_refusal_that_names_no_account_allowance_holds_out_only_that_model(self):
        """The narrow reading stays narrow, or one throttled model retires a provider.

        A refusal that attributes itself to nothing is read as being about the model
        that was asked, because guessing too narrow costs one further attempt to
        learn the same fact while guessing too wide withholds routes the provider
        would have served.
        """
        now = __import__("datetime").datetime.utcnow()
        provider = self.model_id.split("/", 1)[0]
        sibling_id = f"{provider}/coder-sibling"
        event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
            "message": "Too many requests. Please retry shortly.",
            "statusCode": 429,
        }}})
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=f"opencode:{provider}", name="Throttling provider", adapter_id="opencode"))
            session.add(ModelRecord(id=sibling_id, name="Sibling coder", provider=provider, category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now, availability_expires_at=now + __import__("datetime").timedelta(minutes=5)))
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", f"print({event!r}); raise SystemExit(1)"])
            await session.commit()
            await ExecutorCapabilityService().certify(session, sibling_id, {"coding": True}, {"run_id": "sibling"})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        refused_model = dispatched["model"]
        async with AsyncSessionLocal() as session:
            observations = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == f"opencode:{provider}",
            ))).scalars().all()
            await self._requeue(session, self.task_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            decision = await ProjectDispatcherService(None)._select_model(session, task)
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == sibling_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == sibling_id))
            await session.commit()
        survivor = next(model_id for model_id in (self.model_id, sibling_id) if model_id.split("/", 1)[1] != refused_model)

        self.assertEqual(dispatched["receipt"]["provider_refusal"]["refusal_scope"], "model")
        self.assertEqual([(item.scope, item.remaining_value) for item in observations], [(refused_model, 0)])
        self.assertEqual(decision["model_id"], survivor, "Only the model the request was refused for is held out.")

    async def test_a_refused_route_becomes_eligible_again_when_the_observation_lapses(self):
        """The exclusion has to last exactly as long as the fact does.

        An allowance that returns leaves no event behind, so the only honest bound
        is the observation's own expiry. A permanent exclusion would retire a route
        over one spent hour.
        """
        now = __import__("datetime").datetime.utcnow()
        provider = self.model_id.split("/", 1)[0]
        async with AsyncSessionLocal() as session:
            observation = QuotaObservationRecord(
                id=f"quota-{uuid.uuid4().hex[:8]}", provider_instance_id=f"opencode:{provider}",
                scope=self.model_id.split("/", 1)[1], unit="requests", remaining_value=0, source="measured",
                checked_at=now, expires_at=now + __import__("datetime").timedelta(minutes=5),
                evidence=json.dumps({"reason": "provider_refusal"}),
            )
            session.add(observation)
            await session.commit()
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            dispatcher = ProjectDispatcherService(None)
            with self.assertRaises(DomainError):
                await dispatcher._select_model(session, task)
            observation.expires_at = now - __import__("datetime").timedelta(seconds=1)
            await session.commit()
            decision = await dispatcher._select_model(session, task)
            await session.delete(observation)
            await session.commit()
        self.assertEqual(decision["model_id"], self.model_id)

    async def test_route_that_cannot_launch_is_unexecutable_not_incapable(self):
        """A process that never started measured nothing, so it may claim nothing.

        Production evidence 2026-08-20, `run-133922d95108`: a route whose provider
        the isolated executor could not resolve exited 1 in 1.9 seconds having never
        reached the model, and TEMM wrote down that the route could not code, could
        not read and could not write. Excluding the route is right - it cannot run.
        Recording *why* as incapacity is not: that verdict outranks what a real
        earlier execution proved, and it never lapses. The exclusion belongs in
        availability, which expires when the fact does.
        """
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.cli_command = "ai-fleet-executable-that-does-not-exist-4417"
            agent.detected_path = "ai-fleet-executable-that-does-not-exist-4417"
            agent.invocation_args = json.dumps([])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        # A launch failure has to leave the pool by availability, and that hold is
        # withheld while the host is short of memory. See `_calm_host`.
        with _calm_host():
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            certified, _ = await ExecutorCapabilityService().satisfies(session, self.model_id, {"coding"})
            model = await session.get(ModelRecord, self.model_id)
            availability_state = model.availability_state
            availability_evidence = json.loads(model.availability_evidence or "{}")
            await self._requeue(session, self.task_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            with self.assertRaises(DomainError):
                await ProjectDispatcherService(None)._select_model(session, task)
        measurement = dispatched["receipt"]["measurement"]
        self.assertEqual(dispatched["receipt"]["outcome"], "launch_failed")
        self.assertEqual(measurement["classification"], "executor_local_failure")
        self.assertEqual(measurement["reason"], "executor_launch_failed")
        self.assertFalse(measurement["measured"], "A process that never started measured nothing.")
        self.assertFalse(measurement["capability_conclusion_admissible"])
        self.assertEqual([item.capability for item in negative], [], "A launch failure is no measurement of incapacity.")
        self.assertTrue(certified, "Capability proven by an earlier real execution must survive a launch failure.")
        self.assertEqual(availability_state, "unavailable", "The route still has to leave the pool - by availability, not by verdict.")
        self.assertEqual(availability_evidence.get("classification"), "executor_local_failure")
        self.assertEqual(availability_evidence.get("source"), "runtime")

    async def test_route_whose_provider_answered_unusably_leaves_the_pool_without_a_verdict(self):
        """A failure at the provider is not the route's answer either - and still has to stop dispatch.

        Production evidence 2026-08-20, `run-1a23ad2eff63`: with the provider
        configuration propagated into the isolated workspace the CLI did reach the
        provider - one `step_start` where the previous probe had none - and the
        provider answered with a null body the client could not parse. The model was
        never invoked, so nothing about the route was measured. Withdrawing it only
        for failures that happen *below* the provider would leave this one eligible,
        and the next task would buy the same non-measurement over again. So the
        exclusion is recorded here too, and on a shorter TTL than a local
        configuration failure gets: a provider that could not answer may be able to
        in ten minutes, while a config the executor cannot resolve will not repair
        itself between two dispatches.
        """
        events = [
            {"type": "step_start"},
            {"type": "error", "error": {"name": "UnknownError", "data": {"message": "Type validation failed: Value: null."}}},
        ]
        script = ";".join([
            "import json, sys",
            f"sys.stdout.write(chr(10).join(json.dumps(event) for event in {events!r}) + chr(10))",
            "sys.exit(1)",
        ])
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentRecord, self.agent_id)
            agent.invocation_args = json.dumps(["-c", script])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        with unittest.mock.patch.object(ProjectDispatcherService, "_build_argv_with_model", lambda self, agent, prompt, workspace, route: [sys.executable, "-c", script]):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 60, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        dispatched = response.json()["dispatched"][0]
        async with AsyncSessionLocal() as session:
            negative = (await session.execute(select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == self.model_id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            ))).scalars().all()
            certified, _ = await ExecutorCapabilityService().satisfies(session, self.model_id, {"coding"})
            model = await session.get(ModelRecord, self.model_id)
            availability_state = model.availability_state
            availability_evidence = json.loads(model.availability_evidence or "{}")
            observed_ttl = (model.availability_expires_at - model.availability_checked_at).total_seconds()
            await self._requeue(session, self.task_id)
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            with self.assertRaises(DomainError):
                await ProjectDispatcherService(None)._select_model(session, task)
        measurement = dispatched["receipt"]["measurement"]
        self.assertEqual(measurement["classification"], "provider_unavailable")
        self.assertEqual(measurement["reason"], "provider_response_unusable")
        self.assertTrue(measurement["resolution_reached"], "The step that began is what places the failure at the provider.")
        self.assertFalse(measurement["measured"])
        self.assertFalse(measurement["capability_conclusion_admissible"])
        self.assertIn("Type validation failed", measurement["error_events"][0]["message"], "The receipt has to carry what explains the attempt.")
        self.assertEqual([item.capability for item in negative], [], "A provider that could not answer measured no incapacity.")
        self.assertTrue(certified, "Capability proven by an earlier real execution must survive it.")
        self.assertEqual(availability_state, "unavailable", "The route has to stop being selected while the condition stands.")
        self.assertEqual(availability_evidence.get("classification"), "provider_unavailable")
        self.assertEqual(observed_ttl, NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS["provider_unavailable"])
        self.assertLess(observed_ttl, NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS["executor_local_failure"], "A provider outage is the more recoverable of the two.")

    async def test_checkpoint_active_list_excludes_terminal_tasks(self):
        phantom = f"phantom-task-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(OrchestrationTaskRecord(id=phantom, project_id=self.project_id, task_type="implementation", title="Already finished", acceptance_json="[]", state="failed"))
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
            checkpoint.active_task_ids_json = json.dumps([phantom])
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/orchestrations/{self.checkpoint_id}/dispatch", json={"workspace_id": self.workspace_id, "timeout_seconds": 30, "max_tasks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        async with AsyncSessionLocal() as session:
            checkpoint = await session.get(OrchestrationCheckpointRecord, self.checkpoint_id)
            await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id == phantom))
            await session.commit()
        self.assertEqual(json.loads(checkpoint.active_task_ids_json), [], "Terminal tasks must not remain active.")

    async def test_caller_timeout_overrides_task_type_policy_in_both_directions(self):
        dispatcher = __import__("core.ai_fleet.services.project_dispatcher", fromlist=["ProjectDispatcherService"]).ProjectDispatcherService(None)
        self.assertEqual(dispatcher._effective_timeout("implementation", None), 300)
        self.assertEqual(dispatcher._effective_timeout("command", None), 180)
        self.assertEqual(dispatcher._effective_timeout("implementation", 120), 120)
        self.assertEqual(dispatcher._effective_timeout("implementation", 900), 900)

    async def _lapse_fixture_route(self, proven: bool = True):
        """Expire the fixture route's executable evidence, optionally leaving a proven past.

        Evidence has to be inserted directly: `certify` stamps expiry from now, and a
        route whose verification has already lapsed is precisely the case under test.
        """
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        async with AsyncSessionLocal() as session:
            model = await session.get(ModelRecord, self.model_id)
            model.availability_expires_at = now - datetime_module.timedelta(minutes=1)
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == self.model_id))
            if proven:
                for capability in ("coding", "file_read", "file_write"):
                    session.add(ModelCapabilityEvidenceRecord(
                        id=f"cap-{uuid.uuid4().hex[:12]}", model_id=self.model_id, capability=capability,
                        supported=True, score=100, provenance="execution_measured", source_type="execution",
                        source_uri="lapsed-run", evidence="{}",
                        observed_at=now - datetime_module.timedelta(hours=2),
                        expires_at=now - datetime_module.timedelta(hours=1),
                    ))
            await session.commit()

    def _renewal_stub(self, calls: list):
        """Stand in for the tournament, recording its call and certifying as a pass would."""
        async def run_tournament(_self, session, model_id, timeout_per_stage=120, stages=None, exploration=None):
            calls.append({"model_id": model_id, "timeout_per_stage": timeout_per_stage, "stages": stages, "exploration": exploration})
            await ExecutorCapabilityService().certify(session, model_id, {"coding": True, "file_read": True, "file_write": True}, {"run_id": "renewal"})
            return {"model_id": model_id, "tournament_id": "renewal", "positive_capabilities": ["coding", "file_read", "file_write"], "stages": [{"stage_id": stages[0], "passed": True, "run_id": "renewal-run"}]}
        return run_tournament

    async def test_lapsed_route_proven_by_execution_is_renewed_before_selection(self):
        """An expired verification must be re-measured by TEMM, not left for an operator."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        await self._lapse_fixture_route()
        calls = []
        with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
            async with AsyncSessionLocal() as session:
                refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])
        self.assertEqual(calls[0]["stages"], [dispatcher_module.REVERIFY_STAGE_ID], "Renewal must probe only the stage that demonstrates the coding floor.")
        self.assertEqual(calls[0]["timeout_per_stage"], dispatcher_module.REVERIFY_STAGE_TIMEOUT_SECONDS)
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence")
        self.assertTrue(refresh["restored"], refresh)

    async def test_renewal_prefers_the_healthier_route_over_the_most_recently_proven(self):
        """Renewal must be decided by what routes did, not by which was renewed last.

        Recency fed itself: the route renewed last held the newest proof, was therefore
        the only available route, was therefore the only route dispatched, and was
        therefore renewed again. That kept a route which timed out on five consecutive
        NEXA tasks as the fleet's sole executor while healthier proven routes stayed
        lapsed - the queue could only ever be offered the worst measured route.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        healthy_id = f"healthy-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route()
        async with AsyncSessionLocal() as session:
            # Proven longer ago than the fixture route, and never a failure on this
            # project - so recency prefers the fixture route and health prefers this one.
            session.add(ModelRecord(id=healthy_id, name="Healthy coder", provider="healthy-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now - datetime_module.timedelta(hours=4), availability_expires_at=now - datetime_module.timedelta(hours=3)))
            for capability in ("coding", "file_read", "file_write"):
                session.add(ModelCapabilityEvidenceRecord(id=f"cap-{uuid.uuid4().hex[:12]}", model_id=healthy_id, capability=capability, supported=True, score=100, provenance="execution_measured", source_type="execution", source_uri="older-run", evidence="{}", observed_at=now - datetime_module.timedelta(hours=6), expires_at=now - datetime_module.timedelta(hours=5)))
            for index in range(3):
                run_id = f"renewal-timeout-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="renewal-history", project_id=self.project_id, status="timed_out"))
                session.add(RunAttemptRecord(id=f"renewal-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id.in_([self.model_id, healthy_id])))
                await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "renewal-history"))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == healthy_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == healthy_id))
                await session.commit()
        self.assertEqual([item["model_id"] for item in calls], [healthy_id], "The route with no measured failures must be renewed first.")
        self.assertEqual(refresh["model_id"], healthy_id)
        self.assertEqual([item["model_id"] for item in refresh["considered"]], [healthy_id, self.model_id])
        self.assertEqual(refresh["considered"][1]["recent_timeout_or_no_effect"], 3)

    async def test_renewal_prefers_a_reachable_route_over_a_healthier_one_the_provider_refused(self):
        """Defect #62: health cannot see whether the probe will reach the model at all.

        Every measurement `_route_health` reads is a statement about a route that ran,
        and it leaves non-measurement out on purpose - a refused attempt describes an
        account, not a route. So a route the provider has been turning away carries the
        neutral score of an untried one and can rank first on health while being the
        one candidate certain to answer nothing. Both bounds that would hold it out are
        deliberately temporary, so it becomes eligible again while that is still the
        last thing the provider said.

        Production evidence 2026-08-21 22:50:58: `openai/gpt-5.4` keyed (0 timeouts, 3
        recent failures) against `opencode/x-preview-f-free`'s (1, 3) and won on the
        first key, 108 seconds after its spent-allowance observation expired and 3m12s
        after its refusal aged out of the refusal window. It took the queue's one
        renewal, spent 80.2s re-confirming the same 429, measured nothing, and dispatch
        raised `execution_unavailable` - while x-preview-f-free, certified through the
        production path 30 minutes earlier with a floor live for another 28, sat one
        renewal away.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        refused_id = f"refused-provider/coder-{uuid.uuid4().hex[:8]}"
        probe_run = f"turned-away-run-{uuid.uuid4().hex[:8]}"
        history_run = f"reachable-run-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route()
        async with AsyncSessionLocal() as session:
            # Lapsed and proven, with no measured failure on this project at all, so
            # health ranks it ahead of the fixture route.
            session.add(ModelRecord(id=refused_id, name="Refused coder", provider="refused-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now - datetime_module.timedelta(hours=4), availability_expires_at=now - datetime_module.timedelta(hours=3)))
            for capability in ("coding", "file_read", "file_write"):
                session.add(ModelCapabilityEvidenceRecord(id=f"cap-{uuid.uuid4().hex[:12]}", model_id=refused_id, capability=capability, supported=True, score=100, provenance="execution_measured", source_type="execution", source_uri="older-run", evidence="{}", observed_at=now - datetime_module.timedelta(hours=6), expires_at=now - datetime_module.timedelta(hours=5)))
            # Its newest attempt never reached the model, and it is old enough that the
            # refusal window has released it - eligible again, and still the last thing
            # the provider said. No quota observation either, exactly as production had
            # none once the horizon lapsed.
            session.add(TaskRun(id=probe_run, prompt="turned-away", project_id=f"probe-project-{uuid.uuid4().hex[:8]}", status="failed"))
            session.add(RunAttemptRecord(id=f"turned-away-a-{uuid.uuid4().hex[:8]}", run_id=probe_run, attempt_number=1, executor_type="agent", model_id=refused_id, status="failed", outcome="non_zero_exit", error_code="provider_allowance_exhausted", started_at=now - datetime_module.timedelta(minutes=70), completed_at=now - datetime_module.timedelta(minutes=70), receipt_json=json.dumps({"duration_ms": 80210, "provider_refusal": {"status_code": 429, "allowance_exhausted": True}, "measurement": {"classification": "provider_refusal", "measured": False, "reason": "provider_allowance_exhausted"}})))
            # The fixture route is the worse bet on health - it holds the timeout - and
            # the better one on reachability: the model ran for it most recently.
            session.add(TaskRun(id=history_run, prompt="reachable-history", project_id=self.project_id, status="timed_out"))
            session.add(RunAttemptRecord(id=f"reachable-a-{uuid.uuid4().hex[:8]}", run_id=history_run, attempt_number=1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", started_at=now - datetime_module.timedelta(minutes=40), completed_at=now - datetime_module.timedelta(minutes=35), receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            session.add(RunAttemptRecord(id=f"reachable-b-{uuid.uuid4().hex[:8]}", run_id=history_run, attempt_number=2, executor_type="agent", model_id=self.model_id, status="failed", outcome="completed", error_code="acceptance_unsatisfied", started_at=now - datetime_module.timedelta(minutes=20), completed_at=now - datetime_module.timedelta(minutes=18), receipt_json=json.dumps({"duration_ms": 42000, "measurement": {"classification": "model_executed", "measured": True, "reason": "acceptance_failed"}})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id.in_([self.model_id, refused_id])))
                await session.execute(delete(TaskRun).where(TaskRun.id.in_([probe_run, history_run])))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == refused_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == refused_id))
                await session.commit()
        self.assertEqual([item["model_id"] for item in calls], [self.model_id],
                         "The one renewal must go to the route the model last ran for, not to the healthier one the provider turned away.")
        self.assertEqual(refresh["model_id"], self.model_id)
        considered = {item["model_id"]: item for item in refresh["considered"]}
        self.assertTrue(considered[refused_id]["provider_turned_away_on_newest_attempt"])
        self.assertFalse(considered[self.model_id]["provider_turned_away_on_newest_attempt"])
        # Ordering, never exclusion: the refused route is still a candidate, and its
        # health is still the better of the two - which is exactly why health alone
        # chose it.
        self.assertEqual(considered[refused_id]["recent_timeout_or_no_effect"], 0)
        self.assertEqual(considered[self.model_id]["recent_timeout_or_no_effect"], 1)

    async def test_renewal_still_probes_a_failing_route_when_it_is_the_only_proven_one(self):
        """Health orders candidates; it must not exclude the last route the fleet has."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        await self._lapse_fixture_route()
        async with AsyncSessionLocal() as session:
            for index in range(4):
                run_id = f"sole-timeout-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="sole-history", project_id=self.project_id, status="timed_out"))
                session.add(RunAttemptRecord(id=f"sole-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "sole-history"))
                await session.commit()
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])
        self.assertTrue(refresh["restored"], refresh)

    async def test_route_that_can_serve_the_queue_is_never_reprobed(self):
        """Renewal costs a real executor run, so a working route must not trigger one."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        calls = []
        with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
            async with AsyncSessionLocal() as session:
                refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        self.assertIsNone(refresh)
        self.assertEqual(calls, [])

    async def test_renewal_does_not_count_a_refused_route_as_able_to_serve_the_queue(self):
        """Renewal and selection have to agree about which routes can serve work.

        Renewal stands down as soon as it finds one available certified route, and it
        read neither the quota observations that selection reads nor anything else
        about whether the provider would serve that route. So the fleet's only
        certified route being refused for a spent allowance left renewal reporting
        the queue as already served while selection discarded that same route as
        unusable and raised `execution_unavailable`. Nothing dispatched and nothing
        renewed - a deadlock lasting as long as the observation, with healthy proven
        routes one probe away the whole time.

        The refused route is also not itself probed: a provider refusing it for the
        task refuses the probe identically, so renewing it spends a run to learn
        nothing.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        spare_id = f"spare-provider/coder-{uuid.uuid4().hex[:8]}"
        quota_id = f"quota-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            # The fixture route keeps its live certification: it can serve the queue in
            # every respect except the one that matters, which is the case under test.
            session.add(QuotaObservationRecord(id=quota_id, provider_instance_id=f"opencode:{self.model_id.split('/', 1)[0]}", scope=self.model_id.split("/", 1)[1], unit="requests", remaining_value=0, source="measured", checked_at=now, expires_at=now + datetime_module.timedelta(minutes=30)))
            # Proven by execution but lapsed - the route renewal exists to restore.
            session.add(ModelRecord(id=spare_id, name="Spare coder", provider="spare-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="available", availability_checked_at=now - datetime_module.timedelta(hours=2), availability_expires_at=now - datetime_module.timedelta(hours=1)))
            for capability in ("coding", "file_read", "file_write"):
                session.add(ModelCapabilityEvidenceRecord(id=f"cap-{uuid.uuid4().hex[:12]}", model_id=spare_id, capability=capability, supported=True, score=100, provenance="execution_measured", source_type="execution", source_uri="spare-run", evidence="{}", observed_at=now - datetime_module.timedelta(hours=3), expires_at=now - datetime_module.timedelta(hours=2)))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.id == quota_id))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == spare_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == spare_id))
                await session.commit()
        self.assertIsNotNone(refresh, "A refused route cannot serve the queue, so renewal had work to do.")
        self.assertEqual([item["model_id"] for item in calls], [spare_id])
        self.assertEqual(refresh["model_id"], spare_id)
        self.assertNotIn(self.model_id, [item["model_id"] for item in refresh["considered"]], "Probing a route the provider is refusing spends a run to learn nothing.")

    async def test_renewal_does_not_reprobe_a_route_the_provider_just_refused(self):
        """Refusals need their own bound, because they must not be recorded as incapacity.

        A failed probe bounds itself: it records the route's incapacity, which
        withdraws the route from renewal until something re-measures it. A refusal
        measures nothing and so records nothing, which leaves renewal free to pick
        the same refusing route on every dispatch and never reach one that works.
        The refusal on the route's newest attempt is the bound - a fact TEMM
        recorded, not a quota claim the provider never made, so it holds for a
        revoked key exactly as it does for a spent allowance.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        await self._lapse_fixture_route()
        run_id = f"refusal-bound-run-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="refusal-bound", project_id=self.project_id, status="failed"))
            # A key refusal, not an allowance one: no quota observation exists to
            # exclude this route, so only the attempt itself can bound the retry.
            session.add(RunAttemptRecord(id=f"refusal-bound-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="failed", outcome="non_zero_exit", error_code="provider_refused", started_at=now - datetime_module.timedelta(minutes=2), completed_at=now - datetime_module.timedelta(minutes=2), receipt_json=json.dumps({"provider_refusal": {"status_code": 403, "provider_code": "invalid_api_key", "allowance_exhausted": False}})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id))
                await session.execute(delete(TaskRun).where(TaskRun.id == run_id))
                await session.commit()
        self.assertNotIn(self.model_id, [item["model_id"] for item in calls], "Probing a route that just refused spends a run to learn nothing.")
        if refresh is not None:
            self.assertNotIn(self.model_id, [item["model_id"] for item in refresh["considered"]])

    async def test_a_route_that_has_run_since_its_refusal_is_renewable_again(self):
        """The bound lasts as long as the refusal does, and no longer."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        await self._lapse_fixture_route()
        run_id = f"refusal-cleared-run-{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            session.add(TaskRun(id=run_id, prompt="refusal-cleared", project_id=self.project_id, status="failed"))
            session.add(RunAttemptRecord(id=f"refusal-cleared-a-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="failed", outcome="non_zero_exit", error_code="provider_refused", started_at=now - datetime_module.timedelta(minutes=20), completed_at=now - datetime_module.timedelta(minutes=20), receipt_json=json.dumps({"provider_refusal": {"status_code": 429, "allowance_exhausted": False}})))
            # Newer, and served: whatever the provider was refusing, it is not now.
            session.add(RunAttemptRecord(id=f"refusal-cleared-b-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=2, executor_type="agent", model_id=self.model_id, status="failed", outcome="non_zero_exit", error_code="acceptance_unsatisfied", started_at=now - datetime_module.timedelta(minutes=5), completed_at=now - datetime_module.timedelta(minutes=5), receipt_json=json.dumps({"duration_ms": 40000})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id))
                await session.execute(delete(TaskRun).where(TaskRun.id == run_id))
                await session.commit()
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])
        self.assertTrue(refresh["restored"], refresh)

    async def _fleet_probe_candidates(self):
        """The fleet split as the dispatcher splits it, for tests about eligibility.

        Read directly rather than through the probe's `considered` preview, because the
        preview is bounded and the shared test database can hold routes from other
        fixtures - so a candidate's presence is the honest assertion, not its position.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        dispatcher = dispatcher_module.ProjectDispatcherService(None)
        async with AsyncSessionLocal() as session:
            routes = (await session.execute(select(ModelRecord).where(
                ModelRecord.source_type == "external_tool", ModelRecord.source_uri == "opencode-cli",
                ModelRecord.lifecycle_status == "active", ModelRecord.is_active.is_(True),
            ))).scalars().all()
            exhausted = await dispatcher._exhausted_routes(session, now)
            lapsed, never_measured = await dispatcher._probe_candidates(session, routes, exhausted, now)
        return [item[1] for item in lapsed], never_measured

    async def _record_floor_evidence(self, model_id: str, supported: bool, expired: bool):
        """Write execution evidence for the coding floor with a chosen verdict and TTL."""
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        expires_at = now - datetime_module.timedelta(hours=1) if expired else now + datetime_module.timedelta(hours=1)
        async with AsyncSessionLocal() as session:
            for capability in ("coding", "file_read", "file_write"):
                session.add(ModelCapabilityEvidenceRecord(
                    id=f"cap-{uuid.uuid4().hex[:12]}", model_id=model_id, capability=capability,
                    supported=supported, score=100 if supported else 0, provenance="execution_measured",
                    source_type="execution", source_uri="probe-run", evidence="{}",
                    observed_at=now - datetime_module.timedelta(minutes=30), expires_at=expires_at,
                ))
            await session.commit()

    async def test_a_never_measured_route_is_measured_when_no_proven_route_can_be(self):
        """A fleet that cannot measure its own routes for the first time is not self-sufficient.

        Renewal restores a route TEMM has proven before, which is the right bound on
        renewal and was also, silently, the only way any route ever became selectable
        - certification had to come from an operator running the tournament by hand.
        Production evidence 2026-08-19: seven working credentials, 342 discovered
        coding routes, three with any execution history at all, and all three refusing
        or spent. Dispatch raised `execution_unavailable` with 339 unmeasured routes
        behind a gate TEMM could not open itself.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        await self._lapse_fixture_route(proven=False)
        lapsed, never_measured = await self._fleet_probe_candidates()
        self.assertNotIn(self.model_id, lapsed, "The route has never been run, so there is nothing to renew.")
        self.assertIn(self.model_id, never_measured)
        calls = []
        with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
            async with AsyncSessionLocal() as session:
                refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        self.assertEqual(refresh["trigger"], "never_measured_route_bootstrap")
        self.assertEqual(refresh["selection_basis"], "provider_round_robin")
        self.assertEqual([item["model_id"] for item in calls], [refresh["model_id"]], "Exactly one route is measured per dispatch.")
        self.assertIn(refresh["model_id"], never_measured)
        self.assertGreaterEqual(refresh["never_measured_routes"], 1)
        self.assertTrue(refresh["restored"], refresh)

    async def test_a_proven_route_is_renewed_before_an_unknown_one_is_tried(self):
        """A route TEMM has proven is a better bet than one it knows nothing about."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        unknown_id = f"aaa-unknown-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route()
        async with AsyncSessionLocal() as session:
            # Sorts ahead of the fixture route by provider, so only preference for a
            # proven route can keep it from being probed first.
            session.add(ModelRecord(id=unknown_id, name="Unknown coder", provider="aaa-unknown-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == unknown_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == unknown_id))
                await session.commit()
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence")
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])

    async def test_chronic_real_task_failure_yields_the_probe_to_a_never_measured_route(self):
        """Defect #26: a route certifying the floor while failing real work must not monopolise renewal.

        Production evidence 2026-08-20: a free route passed the trivial file-write floor
        on demand yet, on this project's actual tasks, delivered one accepted write
        against eleven failures - most of them timeouts or no-effect runs. Because
        renewal preferred any floor-proven route over an untried one, that route was
        re-measured on every dispatch and the never-measured routes behind it were never
        reached: the queue could only be offered the route that could not do the work.
        Renewal must now see the route is chronically failing real production tasks and -
        an unmeasured route being available to try - yield its one probe to bounded
        bootstrap, recording why and on what evidence, without blacklisting the route it
        yielded (the final fallback below renews it when nothing unmeasured remains).
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        accepted_task_id = f"chronic-accepted-task-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route(proven=True)
        async with AsyncSessionLocal() as session:
            # A never-measured route to yield to: no evidence of any kind, so it is a
            # bootstrap candidate and nothing renewal could pick. It sorts last by
            # provider, so only the yield - not ordering - can cause it to be probed.
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            # One accepted write requires the completed-task join _route_health reads;
            # testing acceptance > 0 guards the rate against a naive "zero accepted" check.
            accepted_run = f"chronic-accepted-run-{uuid.uuid4().hex[:8]}"
            session.add(TaskRun(id=accepted_run, prompt="chronic-history", project_id=self.project_id, status="completed"))
            session.add(RunAttemptRecord(id=f"chronic-accepted-attempt-{uuid.uuid4().hex[:8]}", run_id=accepted_run, attempt_number=1, executor_type="agent", model_id=self.model_id, status="completed", outcome="completed", receipt_json=json.dumps({"duration_ms": 42000})))
            session.add(OrchestrationTaskRecord(id=accepted_task_id, project_id=self.project_id, task_type="implementation", title="Accepted", description="Completed once", requirement_ids_json=json.dumps([self.requirement_id]), acceptance_json="[]", context_refs_json="[]", executor_needs_json='{"capabilities":["coding"]}', state="completed", current_run_id=accepted_run))
            for index in range(11):
                run_id = f"chronic-timeout-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="chronic-history", project_id=self.project_id, status="timed_out"))
                session.add(RunAttemptRecord(id=f"chronic-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "chronic-history"))
                await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id == accepted_task_id))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
                await session.commit()
        # The one probe went to the untried route, and the chronic route was not renewed.
        self.assertEqual(refresh["trigger"], "chronic_renewable_failure_bootstrap")
        self.assertEqual(refresh["selection_basis"], "provider_round_robin")
        self.assertEqual(refresh["model_id"], bootstrap_id)
        self.assertEqual([item["model_id"] for item in calls], [bootstrap_id], "The chronically failing route must not be renewed when an untried route can be measured instead.")
        self.assertGreaterEqual(refresh["never_measured_routes"], 1)
        self.assertTrue(refresh["restored"], refresh)
        # Why exploration happened and the production evidence that caused it - echoed in
        # the refresh and threaded to the tournament so it persists on the probed route.
        exploration = refresh["exploration"]
        self.assertEqual(exploration["reason"], "all_renewable_routes_chronically_failing_real_production_tasks")
        self.assertEqual(exploration["yielded_route"], self.model_id)
        self.assertEqual(exploration["attempts"], 12)
        self.assertEqual(exploration["accepted_file_writes"], 1)
        self.assertEqual(exploration["failed_or_unaccepted"], 11)
        self.assertEqual(exploration["recent_timeout_or_no_effect"], 11)
        self.assertLess(exploration["acceptance_rate"], dispatcher_module.CHRONIC_FAILURE_MAX_ACCEPTANCE_RATE)
        self.assertEqual([route["model_id"] for route in exploration["renewable_routes_considered"]], [self.model_id])
        self.assertEqual(exploration["renewable_routes_considered"][0]["failed_or_unaccepted"], 11)
        self.assertEqual(calls[0]["exploration"]["yielded_route"], self.model_id, "The tournament must receive the exploration record so persistence can carry it onto the probed route.")

    def _refusing_bootstrap_stub(self, calls: list, measured: bool):
        """Stand in for a tournament stage that ran and recorded a receipt.

        `measured` decides the only thing under test: whether the probe reached the
        model. A refusal writes the same shape of receipt a real one does - the
        classification, `measured: false`, and no capability certification, because
        none was measured.
        """
        async def run_tournament(_self, session, model_id, timeout_per_stage=120, stages=None, exploration=None):
            calls.append({"model_id": model_id, "stages": stages, "exploration": exploration})
            run_id = f"probe-run-{uuid.uuid4().hex[:8]}"
            receipt = {"duration_ms": 78233, "measurement": (
                {"classification": "model_executed", "measured": True, "reason": "acceptance_failed"}
                if measured else
                {"classification": "provider_refusal", "measured": False, "reason": "provider_allowance_exhausted"}
            )}
            if not measured:
                receipt["provider_refusal"] = {"status_code": 429, "provider_code": "1113", "allowance_exhausted": True}
            session.add(TaskRun(id=run_id, prompt="probe", project_id=f"tournament-project-{uuid.uuid4().hex[:8]}", status="failed"))
            session.add(RunAttemptRecord(id=f"probe-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=model_id, status="failed", outcome="failed", receipt_json=json.dumps(receipt)))
            await session.commit()
            return {"model_id": model_id, "tournament_id": "probe", "positive_capabilities": [], "stages": [{"stage_id": stages[0], "passed": False, "run_id": run_id}]}
        return run_tournament

    async def _chronic_fixture_with_untried_route(self, bootstrap_id: str):
        """Make the fixture route proven-but-chronic, with one untried route to yield to."""
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        await self._lapse_fixture_route(proven=True)
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            for index in range(6):
                run_id = f"chronic-history-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="chronic-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"chronic-history-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="failed", outcome="failed", receipt_json=json.dumps({"duration_ms": 120000, "measurement": {"classification": "model_executed", "measured": True}})))
            await session.commit()

    async def _clean_chronic_fixture(self, bootstrap_id: str):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id.in_([self.model_id, bootstrap_id])))
            await session.execute(delete(TaskRun).where(TaskRun.prompt.in_(["chronic-history", "probe"])))
            await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
            await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
            await session.commit()

    async def test_a_yield_to_a_route_that_could_not_be_measured_still_renews_the_proven_one(self):
        """Defect #57: a probe that answered nothing must not cost the queue its route.

        The yield to bootstrap is priced on each probe either winning a route or
        eliminating one. A probe that never reached the model does neither: it writes no
        capability evidence by design, so the route it was spent on is exactly as untried
        as before, and the proven route whose renewal was deferred is still proven.
        Reading the mere existence of an unmeasured alternative as the whole precondition
        made the "nothing unmeasured remains" fallback unreachable in precisely the case
        it was written for.

        Production evidence 2026-08-21 21:08:33: of fourteen floor-proven routes, twelve
        were held out by live spent-allowance observations, and the three that remained
        were all chronic on this project - `opencode/x-preview-f-free` at 0 accepted
        writes against 5 measured failures, `openai/gpt-5.4` at 1 against 6, and
        `opencode/deepseek-v4-flash-free` at 3 against 23. So renewal declined every one
        of them and the probe went to `zai/glm-4.5`, which the provider refused for a
        spent allowance in 78.2s (429, provider_code 1113, `measured: false`). Nothing
        was won and nothing eliminated, yet dispatch raised `execution_unavailable`:
        x-preview-f-free's floor was measured at 20:18:47 and valid until 21:18:47, and
        only its 20:48:47 availability lapse stood between the queue and a run.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._chronic_fixture_with_untried_route(bootstrap_id)
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._refusing_bootstrap_stub(calls, measured=False)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            await self._clean_chronic_fixture(bootstrap_id)
        # The yield happened first - it is still the right preference - and then the
        # renewal it deferred was taken, in this dispatch, because it bought nothing.
        self.assertEqual([item["model_id"] for item in calls], [bootstrap_id, self.model_id],
                         "The unmeasurable probe must be followed by the deferred renewal, not by execution_unavailable.")
        self.assertEqual(refresh["model_id"], self.model_id)
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence_after_unmeasurable_bootstrap")
        # The probe that answered nothing is preserved rather than overwritten: the
        # dispatch spent it, and why the renewal happened is only legible with it.
        yielded = refresh["yielded_probe"]
        self.assertEqual(yielded["model_id"], bootstrap_id)
        self.assertEqual(yielded["trigger"], "chronic_renewable_failure_bootstrap")
        self.assertEqual(yielded["exploration"]["yielded_route"], self.model_id)

    async def test_a_bootstrap_probe_that_reached_the_model_and_failed_eliminates_it_and_stops(self):
        """The elimination bound stays exactly as tight for the case it was written for.

        Non-measurement is what reopens the choice, not failure. A probe that reached
        the model and failed has answered: the route is eliminated by its own newest
        execution evidence, the yield bought that, and the chronic route stays deferred
        until the next dispatch. Without this the fix would read as "retry until
        something passes" and spend two probes on every unsuccessful exploration.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._chronic_fixture_with_untried_route(bootstrap_id)
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._refusing_bootstrap_stub(calls, measured=True)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            await self._clean_chronic_fixture(bootstrap_id)
        self.assertEqual([item["model_id"] for item in calls], [bootstrap_id],
                         "A measured failure is an answer, so the probe budget is spent and the chronic route waits.")
        self.assertEqual(refresh["model_id"], bootstrap_id)
        self.assertEqual(refresh["trigger"], "chronic_renewable_failure_bootstrap")
        self.assertNotIn("yielded_probe", refresh)

    async def test_a_host_failure_that_measured_nothing_does_not_make_the_route_chronic(self):
        """Defect #55: a route may only be judged by attempts in which it ran.

        `_route_health` left provider refusals out and counted every other kind of
        non-measurement in full, so a route's record got worse the worse the machine
        under it behaved. That reaches further than ranking, because
        `_chronic_production_failure` reads the same counts to decide whether a route
        may be renewed at all. Production evidence 2026-08-21: attempt-0144bc5d1502
        aborted inside the CLI's own runtime on `MemoryExhaustion` 31s in, exit
        0xC0000409, with no events, no tokens and no diff, and it was
        `opencode/x-preview-f-free`'s fifth recorded failure on NEXA - exactly
        `CHRONIC_FAILURE_MIN_FAILURES`. The fleet's one certified route was declared
        chronic on the strength of this machine's memory, its dispatch yielded the one
        probe to an unmeasured route, and the queue was answered `execution_unavailable`
        while a working route sat lapsed. So the four attempts that measured the route
        are its record, the fifth is not, and renewal goes to the route that has been
        proven rather than to bootstrap.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route(proven=True)
        async with AsyncSessionLocal() as session:
            # Somewhere to yield to, so the assertions distinguish "did not yield" from
            # "had nothing to yield to" - the same fixture the defect #26 case uses.
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            # One short of the chronic threshold, all of them measured: the route ran
            # and left the workspace unchanged. That is its record and it stands. These
            # were acceptance shortfalls until defect #66 established that a shortfall
            # is a statement about the contract rather than about the route, and so is
            # left out of this gate entirely - which would have made the arithmetic
            # here express nothing. A run that produced no effect is the same kind of
            # evidence the aborted attempt below is being distinguished from: measured,
            # and undelivered.
            for index in range(dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES - 1):
                run_id = f"unmeasured-history-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="unmeasured-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"unmeasured-history-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="failed", outcome="completed", error_code="no_effect", receipt_json=json.dumps({"duration_ms": 120000, "no_effect": True, "measurement": {"measured": True, "classification": "model_executed"}})))
            # The attempt that would carry the route over the threshold, in which the
            # route did nothing at all: the executor died before the first model step.
            aborted_run = f"unmeasured-history-run-{uuid.uuid4().hex[:8]}"
            session.add(TaskRun(id=aborted_run, prompt="unmeasured-history", project_id=self.project_id, status="failed"))
            session.add(RunAttemptRecord(id=f"unmeasured-history-attempt-{uuid.uuid4().hex[:8]}", run_id=aborted_run, attempt_number=dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES, executor_type="agent", model_id=self.model_id, status="failed", outcome="failed", error_code="non_zero_exit", receipt_json=json.dumps({"duration_ms": 31335, "measurement": {"measured": False, "classification": "no_execution_signal"}})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    dispatcher = dispatcher_module.ProjectDispatcherService(None)
                    health = await dispatcher._route_health(session, self.project_id)
                    observed = dict(health[self.model_id])
                    refresh = await dispatcher._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "unmeasured-history"))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
                await session.commit()
        # Four attempts measured the route; the fifth measured the machine.
        self.assertEqual(observed["failed"], dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES - 1)
        self.assertEqual(observed["recent_failures"], dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES - 1)
        self.assertEqual(observed["accepted_writes"], 0)
        chronic = dispatcher_module.ProjectDispatcherService._chronic_production_failure
        self.assertFalse(chronic(observed), "Four measured failures are below the threshold, so the route stays renewable.")
        self.assertTrue(chronic({**observed, "failed": observed["failed"] + 1}), "Counting the aborted attempt is what crossed the threshold - the defect this test holds shut.")
        # So the probe renews the proven route instead of yielding it to bootstrap.
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence")
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])
        self.assertIsNone(refresh.get("exploration"), "Nothing was chronically failing, so nothing was yielded.")
        self.assertTrue(refresh["restored"], refresh)

    async def test_an_acceptance_shortfall_does_not_withdraw_a_proven_route_from_renewal(self):
        """Defect #66: chronic status must not be a function of how much work a route got.

        `_chronic_production_failure` counted an acceptance shortfall as the route's own
        failure, so the routes the fleet actually hands work to were the first it
        disqualified - and a route is only handed work because it was performing. A
        shortfall is a completed run whose work did not satisfy a contract TEMM wrote
        and TEMM measures, which is evidence about that contract as much as about the
        route: defect #63 was precisely a delivered, wired, reachable screen recorded as
        a shortfall because acceptance read a re-export instead of the module it
        forwards to.

        Production evidence 2026-08-22 00:23:59. `opencode/x-preview-f-free` - the
        fleet's one certified route, fifty minutes past a run of 72 tool uses, 3.59M
        tokens and eight changed files, holding a coding floor live for another nine -
        sorted first for renewal on reachability and was then dropped here as chronic on
        seven failures: six shortfalls, each classified `model_executed` and satisfying
        one or two of three clauses, and one timeout. The probe went to
        `openai/gpt-5.4-fast` instead, which cleared this gate only by holding four of
        the identical shortfalls rather than five, and whose newest provider interaction
        was a 429; it re-confirmed the 429 in 77s, measured nothing, and the dispatch
        answered `execution_unavailable` with the certified route one renewal away. Both
        routes had failed the same criterion ids, which is what a hard contract looks
        like from every route rather than what one bad route looks like.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route(proven=True)
        shortfalls = dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES + 1
        async with AsyncSessionLocal() as session:
            # Somewhere to yield to, so the assertions distinguish "did not yield" from
            # "had nothing to yield to".
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            # Past the threshold and at zero delivery, so nothing but the kind of
            # failure decides this. Every one of them ran: the route executed, wrote,
            # and the contract was not fully satisfied.
            for index in range(shortfalls):
                run_id = f"shortfall-history-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="shortfall-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"shortfall-history-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="failed", outcome="completed", error_code="acceptance_unsatisfied", receipt_json=json.dumps({"duration_ms": 120000, "measurement": {"measured": True, "classification": "model_executed"}})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    dispatcher = dispatcher_module.ProjectDispatcherService(None)
                    health = await dispatcher._route_health(session, self.project_id)
                    observed = dict(health[self.model_id])
                    refresh = await dispatcher._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id.in_([self.model_id, bootstrap_id])))
                await session.execute(delete(TaskRun).where(TaskRun.prompt.in_(["shortfall-history", "probe"])))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
                await session.commit()
        # Ranking keeps every shortfall, so the route that satisfies more of a contract
        # is still preferred - the fix narrows what may *withdraw* a route, nothing else.
        self.assertEqual(observed["failed"], shortfalls)
        self.assertEqual(observed["recent_failures"], shortfalls)
        self.assertEqual(observed["unmet_contract"], shortfalls)
        self.assertEqual(observed["accepted_writes"], 0)
        chronic = dispatcher_module.ProjectDispatcherService._chronic_production_failure
        self.assertFalse(chronic(observed), "A shortfall is not a run the route failed to deliver, so it cannot make the route chronic.")
        self.assertTrue(chronic({**observed, "unmet_contract": 0}), "Counting the shortfalls as undelivered runs is the defect this test holds shut.")
        # And the gate keeps its teeth: the same count of runs the route failed to
        # deliver still withdraws it.
        self.assertTrue(chronic({**observed, "unmet_contract": observed["failed"] - dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES}),
                        "Timeouts, non-zero exits and no-effect runs must still make a route chronic.")
        # So the queue's one probe renews the proven route rather than yielding it.
        self.assertEqual([item["model_id"] for item in calls], [self.model_id],
                         "The proven route must be renewed, not passed over for an untried one on the strength of its shortfalls.")
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence")
        self.assertIsNone(refresh.get("exploration"), "Nothing was chronically failing, so nothing was yielded.")
        self.assertTrue(refresh["restored"], refresh)
        # The renewal record says which of the two the failures were, because reading a
        # single `failed_or_unaccepted` count is what made this incident need forensics.
        record = next(item for item in refresh["considered"] if item["model_id"] == self.model_id)
        self.assertEqual(record["unmet_acceptance_contract"], shortfalls)
        self.assertEqual(record["undelivered_runs"], 0)

    async def test_a_timeout_that_delivered_work_does_not_withdraw_a_proven_route_from_renewal(self):
        """Defect #80: TEMM picks the clock, so being stopped by it is not the route's answer.

        The ceiling is a dispatch parameter - the caller's guess at how long a task should
        need - so a run stopped at it says the guess was short or the task was large, and
        those are indistinguishable from the route's side. What makes a timeout the
        route's own answer is producing nothing, and that case is held by
        `test_a_timeout_that_changed_nothing_or_measured_nothing_still_counts_as_undelivered`.

        The contradiction was internal, which is why it survived #66. The very receipts
        this gate counted against the route also *renew* its capability floor: they are
        classified `model_executed` with a workspace diff, tool calls and token usage, so
        one reader of an attempt said "this route demonstrably codes, renew coding,
        file_read and file_write" while another said "this route failed to deliver, count
        it toward withdrawal".

        Production evidence 2026-08-22 08:13:45. `opencode/x-preview-f-free` held five
        such runs on project-23a514f0c426 - ceilings of 600s, 900s, 1500s, 3000s and
        3602s, four of them changing 1, 1, 2 and 8 files - and attempt-30f37bfabca5, the
        newest, had renewed all three floor capabilities 72 minutes earlier. `lapsed` held
        exactly three routes; `renewal_order` ranked the certified route first on
        reachability and `openai/gpt-5.4` last, its newest provider interaction a 429 and
        its floor proven 30 hours before. This gate excluded both `opencode` routes, which
        promoted the route ordering had ranked last to `renewable[0]`. The dispatch spent
        its single probe re-confirming that 429 in 79s, measured nothing, eliminated
        nothing, and answered the queue `execution_unavailable` with the certified route
        one renewal away - and would have done so on every dispatch after it, because the
        exclusion is recomputed from the same unchanging history each time.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route(proven=True)
        cut_short = dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES + 1
        async with AsyncSessionLocal() as session:
            # Somewhere to yield to, so the assertions distinguish "did not yield" from
            # "had nothing to yield to".
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            # Past the threshold and at zero delivery, so nothing but the kind of failure
            # decides this. Every one of them reached the model and was writing when the
            # clock ran out, at ceilings TEMM itself chose and lengthened.
            for index in range(cut_short):
                run_id = f"cut-short-history-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="cut-short-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"cut-short-history-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", error_code="execution_timeout", receipt_json=json.dumps({
                    "duration_ms": 600000 + index * 300000,
                    "no_effect": False,
                    "workspace_diff": [{"path": "frontend/src/pages/OrdersPage.tsx", "before": None, "after": "sha", "change": "added"}],
                    "measurement": {"measured": True, "classification": "model_executed"},
                })))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    dispatcher = dispatcher_module.ProjectDispatcherService(None)
                    health = await dispatcher._route_health(session, self.project_id)
                    observed = dict(health[self.model_id])
                    refresh = await dispatcher._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id.in_([self.model_id, bootstrap_id])))
                await session.execute(delete(TaskRun).where(TaskRun.prompt.in_(["cut-short-history", "probe"])))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
                await session.commit()
        # Ranking keeps every one of them, exactly as #66 left the shortfalls: a route
        # that keeps running out of clock is still ordered behind one that does not. The
        # fix narrows what may *withdraw* a route and nothing else.
        self.assertEqual(observed["failed"], cut_short)
        self.assertEqual(observed["recent_failures"], cut_short)
        self.assertEqual(observed["timeout_no_effect"], cut_short)
        self.assertEqual(observed["cut_short"], cut_short)
        self.assertEqual(observed["accepted_writes"], 0)
        chronic = dispatcher_module.ProjectDispatcherService._chronic_production_failure
        self.assertFalse(chronic(observed), "A run stopped by TEMM's own ceiling while delivering work is not a run the route failed to deliver.")
        self.assertTrue(chronic({**observed, "cut_short": 0}), "Counting them as undelivered runs is the defect this test holds shut.")
        # And the gate keeps its teeth: the same count of runs the route really failed to
        # deliver still withdraws it.
        self.assertTrue(chronic({**observed, "cut_short": observed["failed"] - dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES}),
                        "Non-zero exits and runs that reached the ceiling having written nothing must still make a route chronic.")
        # So the queue's one probe renews the proven route rather than yielding it to an
        # untried one - which is the whole of what the incident cost.
        self.assertEqual([item["model_id"] for item in calls], [self.model_id],
                         "The proven route must be renewed, not passed over on the strength of ceilings TEMM chose.")
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence")
        self.assertIsNone(refresh.get("exploration"), "Nothing was chronically failing, so nothing was yielded.")
        self.assertTrue(refresh["restored"], refresh)
        # The renewal record says which of the two the failures were, for the same reason
        # #66 added its counter: reading a single `failed_or_unaccepted` count is what
        # made this incident need forensics.
        record = next(item for item in refresh["considered"] if item["model_id"] == self.model_id)
        self.assertEqual(record["runs_cut_short_by_ceiling"], cut_short)
        self.assertEqual(record["undelivered_runs"], 0)

    async def test_a_timeout_that_changed_nothing_or_measured_nothing_still_counts_as_undelivered(self):
        """The other half of #80, and the reason it discriminates rather than forgives.

        A run that reached the ceiling having written no file is undelivered however
        generous the allowance was, so the effect is what is tested and `no_effect` is not
        enough on its own to find it - attempt-df279e00dbda timed out at 3000s with an
        empty diff and `no_effect: false`. A legacy receipt carrying no measurement is
        counted as it always was, exactly as the `unmet_contract` line above it promises,
        because an attempt from before measurement was recorded cannot say whether the
        model was writing when the clock stopped.

        Re-scored across every route on project-23a514f0c426, exactly one verdict changed:
        `opencode/deepseek-v4-flash-free` stays chronic on 23 undelivered runs, five of
        them timeouts that changed nothing and none cut short, and `opencode/big-pickle`
        stays chronic on six.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        empty = dispatcher_module.CHRONIC_FAILURE_MIN_FAILURES
        async with AsyncSessionLocal() as session:
            for index in range(empty):
                run_id = f"no-effect-timeout-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="no-effect-timeout-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"no-effect-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", error_code="execution_timeout", receipt_json=json.dumps({
                    "duration_ms": 3000000,
                    "no_effect": False,
                    "workspace_diff": [],
                    "measurement": {"measured": True, "classification": "model_executed"},
                })))
            # One from before measurement was recorded, with an effect: unattributable, so
            # counted as it always was rather than excused by the new distinction.
            legacy_run = f"no-effect-timeout-run-{uuid.uuid4().hex[:8]}"
            session.add(TaskRun(id=legacy_run, prompt="no-effect-timeout-history", project_id=self.project_id, status="failed"))
            session.add(RunAttemptRecord(id=f"no-effect-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=legacy_run, attempt_number=empty + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", error_code="execution_timeout", receipt_json=json.dumps({
                "duration_ms": 900000,
                "workspace_diff": [{"path": "backend/src/index.js", "before": "sha", "after": "sha2", "change": "modified"}],
            })))
            await session.commit()
        try:
            async with AsyncSessionLocal() as session:
                dispatcher = dispatcher_module.ProjectDispatcherService(None)
                health = await dispatcher._route_health(session, self.project_id)
                observed = dict(health[self.model_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                await session.execute(delete(TaskRun).where(TaskRun.prompt == "no-effect-timeout-history"))
                await session.commit()
        self.assertEqual(observed["failed"], empty + 1)
        self.assertEqual(observed["cut_short"], 0, "Neither an empty diff nor an unmeasured receipt may be read as work in progress.")
        chronic = dispatcher_module.ProjectDispatcherService._chronic_production_failure
        self.assertTrue(chronic(observed), "These are runs the route failed to deliver, and the gate must still withdraw it.")

    async def test_a_timeout_that_did_none_of_its_directed_work_is_not_credited_as_delivering(self):
        """Defect #81: #80's excuse tested for any change, so it excused doing the wrong work.

        A run stopped at TEMM's own ceiling is excused because the ceiling is TEMM's
        guess, and the evidence that the guess was short is that the route was
        delivering when the clock ran out. `bool(workspace_diff)` is not that evidence.
        It is true of a run that spent its whole allowance on files nobody asked for,
        which is the route's answer and not the clock's.

        Production evidence 2026-08-22 12:03:44. attempt-d2389464cdd4 on
        task-25653b8e4130 was directed at four deletions - `__inspect_db.cjs`,
        `debug-db.js`, `seed.js`, `seed-data.js` - reached the 1200s ceiling having
        performed none of them, and changed seven files its focus named nowhere
        (`DISTRIBUTABLE_PACKAGE.md`, `PACKAGE_RELEASE_NOTES.md`, `TESTS_BUILD_START.md`,
        `backend/vitest.config.ts`, `frontend/vite.config.ts`,
        `scripts/build-package.js`, `verify-e2e.js`). Its own receipt reads
        `focus_adherence.verdict: "touched_none"`, `removals_performed: []`,
        `removals_outstanding` all four - and #80 credited it as a route delivering
        work. `focus_adherence` measures exactly the question the excuse assumes an
        answer to, so the excuse is conditioned on it.

        Re-scored over project-23a514f0c426 the correction moves the certified route's
        undelivered count from 1 to 2 and changes no verdict: the guard is against the
        excuse hollowing out as such runs accumulate, not a live withdrawal.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        directed = ["seed.js", "seed-data.js"]
        elsewhere = [{"path": "PACKAGE_RELEASE_NOTES.md", "before": None, "after": "sha", "change": "added"}]
        shapes = {
            # Told to delete two files, deleted neither, changed something else.
            "touched_none": {"stated": [], "touched": [], "verdict": "touched_none", "removals_stated": directed, "removals_performed": [], "removals_outstanding": directed},
            # Deleted one of the two before the clock stopped: progress on the directed work.
            "touched_some": {"stated": [], "touched": [], "verdict": "touched_some", "removals_stated": directed, "removals_performed": ["seed.js"], "removals_outstanding": ["seed-data.js"]},
            # TEMM stated no focus, so the run cannot be charged for missing one.
            "no_focus_stated": {"stated": [], "touched": [], "verdict": "no_focus_stated", "removals_stated": [], "removals_performed": [], "removals_outstanding": []},
        }

        async def health_for(receipt: dict) -> dict:
            run_id = f"focus-credit-run-{uuid.uuid4().hex[:8]}"
            async with AsyncSessionLocal() as session:
                session.add(TaskRun(id=run_id, prompt="focus-credit-history", project_id=self.project_id, status="failed"))
                session.add(RunAttemptRecord(id=f"focus-credit-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", error_code="execution_timeout", receipt_json=json.dumps(receipt)))
                await session.commit()
            try:
                async with AsyncSessionLocal() as session:
                    health = await dispatcher_module.ProjectDispatcherService(None)._route_health(session, self.project_id)
                    return dict(health[self.model_id])
            finally:
                async with AsyncSessionLocal() as session:
                    await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                    await session.execute(delete(TaskRun).where(TaskRun.prompt == "focus-credit-history"))
                    await session.commit()

        base = {"duration_ms": 1200189, "no_effect": False, "workspace_diff": elsewhere, "measurement": {"measured": True, "classification": "model_executed"}}
        expected = {"touched_none": 0, "touched_some": 1, "no_focus_stated": 1}
        for verdict, adherence in shapes.items():
            with self.subTest(verdict=verdict):
                observed = await health_for({**base, "focus_adherence": adherence})
                self.assertEqual(observed["failed"], 1)
                self.assertEqual(
                    observed["cut_short"], expected[verdict],
                    "A diff that made no progress on the directed work is not evidence the ceiling was short."
                    if verdict == "touched_none" else
                    "Progress on the directed work, or no directive to measure against, keeps the excuse.",
                )

        # A receipt written before this reading existed keeps the credit #80 gave it: the
        # missing measurement is a gap in TEMM's evidence and is not charged to the route.
        legacy = await health_for(base)
        self.assertEqual(observed_legacy := legacy["cut_short"], 1, observed_legacy)

    async def test_a_route_measured_unexecutable_is_held_out_until_that_observation_lapses(self):
        """A probe that measured nothing must still not be repeated on every dispatch.

        Bootstrap is bounded by elimination: a failed probe records the route's
        incapacity as its newest execution evidence, which withdraws it, so each probe
        either wins a route or removes one. That bound only holds when the model
        actually ran. For the failures where it did not - provider unresolvable from
        the executor's configuration, model unknown to the CLI, provider rejecting the
        client or answering unusably - no capability evidence is written at all, which
        is the correct outcome and leaves bootstrap with no memory: the route looks
        exactly like one never tried, so the fleet's one probe per dispatch returns to
        it and the routes behind it are never reached. Production evidence 2026-08-20:
        `agentrouter-openai/claude-opus-4-8` reached its provider and got an unparseable
        body back (`run-1a23ad2eff63`, 18.7s, `provider_response_unusable`) - a
        condition no number of re-probes changes.

        So the bound for those is the runtime unavailability observation the attempt
        records in place of the false verdict, and it has to be read in both
        directions: held out while the observation is live, a candidate again once it
        lapses. Permanent withdrawal would retire a route over a ten-minute provider
        fault, which is the same mistake as the incapacity verdict in a slower form.
        """
        datetime_module = __import__("datetime")

        async def observe_unexecutable(live: bool):
            """Record what a non-measurement records: unavailable, with a bounded TTL."""
            now = datetime_module.datetime.utcnow()
            async with AsyncSessionLocal() as session:
                model = await session.get(ModelRecord, self.model_id)
                model.availability_state = "unavailable"
                model.availability_checked_at = now
                model.availability_expires_at = now + datetime_module.timedelta(seconds=600 if live else -600)
                model.availability_evidence = json.dumps({
                    "source": "runtime", "run_id": "run-1a23ad2eff63",
                    "classification": "provider_unavailable", "reason": "provider_response_unusable",
                })
                await session.commit()

        for proven in (True, False):
            with self.subTest(proven=proven):
                await self._lapse_fixture_route(proven=proven)
                await observe_unexecutable(live=True)
                lapsed, never_measured = await self._fleet_probe_candidates()
                self.assertNotIn(self.model_id, never_measured, "A route measured unexecutable is not a route never tried.")
                self.assertNotIn(self.model_id, lapsed, "Nor is a past proof reason to re-probe it while it cannot run.")
                await observe_unexecutable(live=False)
                lapsed, never_measured = await self._fleet_probe_candidates()
                self.assertIn(
                    self.model_id, lapsed if proven else never_measured,
                    "The bound is the condition, not a retirement - it has to expire with the observation.",
                )

        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        await self._lapse_fixture_route(proven=True)
        await observe_unexecutable(live=True)
        calls = []
        with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
            async with AsyncSessionLocal() as session:
                refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        self.assertNotIn(
            self.model_id, [item["model_id"] for item in calls],
            "The dispatch's one probe must not go back to a route just measured unexecutable.",
        )
        if refresh:
            self.assertNotEqual(refresh["model_id"], self.model_id, refresh)

    async def test_a_still_delivering_route_is_renewed_though_it_sometimes_fails(self):
        """The gate is a delivery rate, not a failure count: a route doing real work is kept.

        Requirement (4)/(5) of defect #26: yielding to bootstrap is a preference driven by
        chronic failure, never a blacklist. A route with the same failure count as the
        chronic case but enough accepted writes to stay above the delivery floor is still
        renewed ahead of an untried route - otherwise any busy route would be abandoned
        the moment an unmeasured alternative appeared, which is the recency trap in a new
        disguise. Because chronic status is recomputed from current health every dispatch,
        a route that resumes delivering stops being chronic with nothing reset by hand.
        """
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        bootstrap_id = f"zzz-bootstrap-provider/coder-{uuid.uuid4().hex[:8]}"
        created_task_ids = []
        await self._lapse_fixture_route(proven=True)
        async with AsyncSessionLocal() as session:
            session.add(ModelRecord(id=bootstrap_id, name="Bootstrap coder", provider="zzz-bootstrap-provider", category="coding", source_type="external_tool", source_uri="opencode-cli", availability_state="unknown", availability_checked_at=now, availability_expires_at=now + datetime_module.timedelta(minutes=5)))
            # Five failures - the chronic count - but four accepted writes, a 0.44 delivery
            # rate that clears the floor: this route is failing, not chronically failing.
            for _ in range(4):
                run_id = f"deliver-accepted-run-{uuid.uuid4().hex[:8]}"
                task_id = f"deliver-accepted-task-{uuid.uuid4().hex[:8]}"
                created_task_ids.append(task_id)
                session.add(TaskRun(id=run_id, prompt="deliver-history", project_id=self.project_id, status="completed"))
                session.add(RunAttemptRecord(id=f"deliver-accepted-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=1, executor_type="agent", model_id=self.model_id, status="completed", outcome="completed", receipt_json=json.dumps({"duration_ms": 42000})))
                session.add(OrchestrationTaskRecord(id=task_id, project_id=self.project_id, task_type="implementation", title="Accepted", description="Completed", requirement_ids_json=json.dumps([self.requirement_id]), acceptance_json="[]", context_refs_json="[]", executor_needs_json='{"capabilities":["coding"]}', state="completed", current_run_id=run_id))
            for index in range(5):
                run_id = f"deliver-timeout-run-{uuid.uuid4().hex[:8]}"
                session.add(TaskRun(id=run_id, prompt="deliver-history", project_id=self.project_id, status="timed_out"))
                session.add(RunAttemptRecord(id=f"deliver-timeout-attempt-{uuid.uuid4().hex[:8]}", run_id=run_id, attempt_number=index + 1, executor_type="agent", model_id=self.model_id, status="timed_out", outcome="timed_out", receipt_json=json.dumps({"duration_ms": 180000, "no_effect": True})))
            await session.commit()
        calls = []
        try:
            with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", self._renewal_stub(calls)):
                async with AsyncSessionLocal() as session:
                    refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.model_id == self.model_id))
                await session.execute(delete(TaskRun).where(TaskRun.project_id == self.project_id, TaskRun.prompt == "deliver-history"))
                await session.execute(delete(OrchestrationTaskRecord).where(OrchestrationTaskRecord.id.in_(created_task_ids)))
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == bootstrap_id))
                await session.execute(delete(ModelRecord).where(ModelRecord.id == bootstrap_id))
                await session.commit()
        self.assertEqual(refresh["trigger"], "lapsed_execution_evidence", "A route delivering above the floor is renewed, not bootstrapped past.")
        self.assertEqual([item["model_id"] for item in calls], [self.model_id])
        self.assertNotIn("exploration", refresh, "No yield occurred, so no exploration record accompanies the renewal.")
        self.assertNotIn(bootstrap_id, [item["model_id"] for item in calls], "An untried route is not probed while a delivering route can be renewed.")

    async def test_a_route_measured_as_incapable_is_never_bootstrapped_again(self):
        """Each probe must either win a route or eliminate one, or the fleet never converges.

        Elimination is what bounds bootstrap to one probe per route rather than one
        per dispatch. Expiry is deliberately not read: a lapsed failure does not
        un-run the execution that produced it, and treating it as un-measured would
        put every failed route back in the queue an hour later, forever.
        """
        for expired in (False, True):
            with self.subTest(expired=expired):
                await self._lapse_fixture_route(proven=False)
                await self._record_floor_evidence(self.model_id, supported=False, expired=expired)
                lapsed, never_measured = await self._fleet_probe_candidates()
                self.assertNotIn(self.model_id, never_measured, "TEMM ran this route against the floor and it failed.")
                self.assertNotIn(self.model_id, lapsed)

    async def test_a_partly_measured_route_is_still_a_bootstrap_candidate(self):
        """One stage of the floor passed is not the floor proven, and not a failure either."""
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        await self._lapse_fixture_route(proven=False)
        async with AsyncSessionLocal() as session:
            session.add(ModelCapabilityEvidenceRecord(id=f"cap-{uuid.uuid4().hex[:12]}", model_id=self.model_id, capability="file_read", supported=True, score=100, provenance="execution_measured", source_type="execution", source_uri="partial-run", evidence="{}", observed_at=now - datetime_module.timedelta(hours=2), expires_at=now - datetime_module.timedelta(hours=1)))
            await session.commit()
        lapsed, never_measured = await self._fleet_probe_candidates()
        self.assertNotIn(self.model_id, lapsed, "Part of the floor is not the floor.")
        self.assertIn(self.model_id, never_measured)

    async def test_a_spent_allowance_excludes_a_route_from_bootstrap_too(self):
        """A provider refusing this route for the task refuses the probe identically."""
        datetime_module = __import__("datetime")
        now = datetime_module.datetime.utcnow()
        quota_id = f"quota-{uuid.uuid4().hex[:8]}"
        await self._lapse_fixture_route(proven=False)
        async with AsyncSessionLocal() as session:
            session.add(QuotaObservationRecord(id=quota_id, provider_instance_id=f"opencode:{self.model_id.split('/', 1)[0]}", scope="*", unit="requests", remaining_value=0, source="measured", checked_at=now, expires_at=now + datetime_module.timedelta(minutes=30)))
            await session.commit()
        try:
            lapsed, never_measured = await self._fleet_probe_candidates()
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.id == quota_id))
                await session.commit()
        self.assertNotIn(self.model_id, never_measured)
        self.assertNotIn(self.model_id, lapsed)

    async def test_bootstrap_tries_every_provider_before_trying_any_twice(self):
        """Routes share credentials by provider, so depth-first spends a fleet on one key.

        Nothing on the evidence TEMM holds distinguishes one never-measured route from
        another - a discovered OpenCode route carries no coding or quality score - so
        the order cannot come from quality. It comes from the one thing that is known:
        consecutive routes from one provider are the likeliest to fail for the same
        reason, so a hundred probes would go to one revoked key before reaching the
        next credential.
        """
        from core.ai_fleet.services.project_dispatcher import DEFAULT_CONTEXT_PACK_TOKENS, ProjectDispatcherService
        ordered = ProjectDispatcherService._provider_round_robin([
            "big/m3", "big/m1", "big/m2", "big/m4", "small/only", "mid/b", "mid/a",
        ])
        self.assertEqual(ordered, ["big/m1", "mid/a", "small/only", "big/m2", "mid/b", "big/m3", "big/m4"])
        self.assertEqual(ProjectDispatcherService._provider_round_robin([]), [])

    async def test_certification_queue_never_triggers_renewal(self):
        """The tournament dispatches through this path, so renewing for it would recurse."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        await self._lapse_fixture_route()
        async with AsyncSessionLocal() as session:
            task = await session.get(OrchestrationTaskRecord, self.task_id)
            task.executor_needs_json = json.dumps({"capabilities": ["coding"], "certification_model_id": self.model_id})
            await session.commit()
            requirements = await dispatcher_module.ProjectDispatcherService(None)._selection_requirements(session, [self.task_id])
            task.executor_needs_json = json.dumps({"capabilities": ["coding"]})
            await session.commit()
        self.assertEqual(requirements, [])

    async def test_renewal_that_fails_is_reported_without_replacing_the_selection_error(self):
        """A failed probe is evidence; the authoritative outcome is still selection's."""
        from core.ai_fleet.services import project_dispatcher as dispatcher_module
        from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
        await self._lapse_fixture_route()

        async def explode(_self, session, model_id, timeout_per_stage=120, stages=None, exploration=None):
            raise RuntimeError("probe crashed")

        with unittest.mock.patch.object(StagedCapabilityTournamentService, "run_tournament", explode):
            async with AsyncSessionLocal() as session:
                refresh = await dispatcher_module.ProjectDispatcherService(None)._reverify_lapsed_routes(session, [self.task_id])
                # The session must survive the failure: dispatch keeps using it.
                self.assertIsNotNone(await session.get(OrchestrationTaskRecord, self.task_id))
        self.assertFalse(refresh["restored"])
        self.assertIn("probe crashed", refresh["error"])


if __name__ == "__main__":
    unittest.main()
