"""Whether the machine can host a run, and whose fault it is when it could not.

TEMM reported on the provider, the credentials, the workspace and the PTY, and never
on the machine all four run on. So a host condition had to arrive wearing borrowed
clothes: the executor died before a model step, the attempt was classified
`executor_local_failure` - accurately, the failure was local - and the route was
withdrawn from selection for half an hour for it.

Production evidence 2026-08-21, `attempt-0144bc5d1502`: the CLI aborted in its own
runtime on `MemoryExhaustion` 31 seconds in, exit `0xC0000409`, no events, no tokens,
no diff. It was the fifth recorded failure for `opencode/x-preview-f-free` on the NEXA
project, and that route was the fleet's only certified one. The route was never asked.

These tests pin down the two halves that keeps apart, because conflating them is how a
gate starts refusing hosts that work. Measured on this machine: a run aborted on memory
with 0.95 GB physical available, and another was admitted at 0.77 GB and ran for over
an hour. So available physical memory does not predict the abort, a floor on it would
have refused the run that worked, and `sufficient` is reserved for the one condition
that genuinely cannot be served - no room in memory and none in the page file.
`pressure` is the softer reading, and it decides nothing about whether to run: it exists
only so a local failure can decline to blame a route for a machine-wide condition.
"""

import unittest
import unittest.mock

import core.ai_fleet.engine.execution_readiness as readiness
from core.ai_fleet.engine.host_capacity import (
    COMMIT_FLOOR_BYTES,
    MEMORY_PRESSURE_FLOOR_BYTES,
    host_capacity,
    host_observation,
)
from core.ai_fleet.errors import DomainError
from core.ai_fleet.services.measurement import (
    EXECUTOR_LOCAL_FAILURE,
    MODEL_EXECUTED,
    NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS,
    NO_EXECUTION_SIGNAL,
    PROVIDER_UNAVAILABLE,
    non_measurement_hold,
)
from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService
from core.ai_fleet.storage.models import ModelRecord, OrchestrationTaskRecord

GIB = 1024 ** 3


def _memory(available, total=16 * GIB):
    return unittest.mock.Mock(available=available, total=total, percent=100 * (1 - available / total))


def _swap(free, total=32 * GIB):
    return unittest.mock.Mock(free=free, total=total)


def _capacity(available, swap_free):
    with unittest.mock.patch("core.ai_fleet.engine.host_capacity.psutil") as psutil:
        psutil.virtual_memory.return_value = _memory(available)
        psutil.swap_memory.return_value = _swap(swap_free)
        return host_capacity()


def _measurement(classification, *, resolution_reached=False):
    return {
        "classification": classification,
        "measured": classification == MODEL_EXECUTED,
        "resolution_reached": resolution_reached,
        "error_events": [],
        "reason": "test",
    }


def _host(*, pressure, measurable=True):
    return {"measurable": measurable, "pressure": pressure, "pressure_basis": "test_basis", "sufficient": True}


class HostCapacityTests(unittest.TestCase):
    """What the reading says, and what it refuses to say."""

    def test_a_host_with_room_is_sufficient_and_unpressured(self):
        capacity = _capacity(available=4 * GIB, swap_free=20 * GIB)
        self.assertTrue(capacity["sufficient"])
        self.assertFalse(capacity["pressure"])
        self.assertIsNone(capacity["reason"])

    def test_only_memory_and_pagefile_together_running_out_disqualifies_a_host(self):
        """The condition an allocation genuinely cannot survive, and nothing weaker."""
        capacity = _capacity(available=COMMIT_FLOOR_BYTES // 4, swap_free=COMMIT_FLOOR_BYTES // 4)
        self.assertFalse(capacity["sufficient"])
        self.assertEqual(capacity["reason"], "host_memory_and_pagefile_exhausted")
        self.assertIn("page file", capacity["detail"])

    def test_the_available_memory_that_aborted_a_run_does_not_refuse_the_next_one(self):
        """0.95 GB available aborted a run and 0.77 GB ran for an hour, so this reading
        cannot be a gate. It is reported as pressure and admitted anyway."""
        capacity = _capacity(available=int(0.77 * GIB), swap_free=25 * GIB)
        self.assertTrue(capacity["sufficient"], "A host measured to run fine is not refused.")
        self.assertTrue(capacity["pressure"])
        self.assertLess(capacity["memory_available_bytes"], MEMORY_PRESSURE_FLOOR_BYTES)

    def test_pressure_and_sufficiency_are_independent_readings(self):
        capacity = _capacity(available=int(0.5 * GIB), swap_free=25 * GIB)
        self.assertTrue(capacity["sufficient"])
        self.assertTrue(capacity["pressure"])
        self.assertIn("observed_abort_level", capacity["pressure_basis"])

    def test_a_host_that_cannot_be_read_is_not_a_host_that_failed(self):
        """Absence of measurement is not evidence, here as everywhere else."""
        with unittest.mock.patch("core.ai_fleet.engine.host_capacity.psutil") as psutil:
            psutil.virtual_memory.side_effect = OSError("no counters")
            capacity = host_capacity()
        self.assertFalse(capacity["measurable"])
        self.assertTrue(capacity["sufficient"], "An unreadable host is admitted, not refused.")
        self.assertFalse(capacity["pressure"], "And it never attributes anything either.")

    def test_the_observation_carried_on_a_receipt_is_bounded_and_holds_no_secrets(self):
        observation = host_observation()
        self.assertEqual(
            set(observation),
            {"measurable", "sufficient", "reason", "pressure", "pressure_basis",
             "memory_available_bytes", "memory_total_bytes", "memory_percent_used",
             "swap_free_bytes", "commit_available_bytes", "observed_at"},
        )
        self.assertTrue(all(isinstance(value, (bool, int, float, str, type(None))) for value in observation.values()))


class HostAttributionTests(unittest.TestCase):
    """Which non-measurements the host may take the blame for, and which it may not."""

    def test_a_local_failure_under_host_pressure_costs_the_route_nothing(self):
        """The machine failed and the route was never asked, so there is nothing to
        withdraw - and withdrawing it would move dispatch onto a route that dies the
        same way, one route at a time down the catalog."""
        hold = non_measurement_hold(_measurement(EXECUTOR_LOCAL_FAILURE), _host(pressure=True))
        self.assertIsNone(hold["ttl_seconds"])
        self.assertEqual(hold["attribution"], "host")
        self.assertEqual(hold["attribution_basis"], "test_basis")
        self.assertTrue(hold["host_observation"]["pressure"])

    def test_the_same_local_failure_on_a_calm_host_still_withdraws_the_route(self):
        """A provider TEMM cannot resolve from the workspace will not resolve on the
        next task either, and that hold is the mechanism that stops re-buying it."""
        hold = non_measurement_hold(_measurement(EXECUTOR_LOCAL_FAILURE), _host(pressure=False))
        self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[EXECUTOR_LOCAL_FAILURE])
        self.assertEqual(hold["attribution"], "route")

    def test_an_unmeasurable_host_withholds_nothing(self):
        """The excuse has to be observed to be used."""
        hold = non_measurement_hold(_measurement(EXECUTOR_LOCAL_FAILURE), _host(pressure=True, measurable=False))
        self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[EXECUTOR_LOCAL_FAILURE])
        self.assertEqual(hold["attribution"], "route")

    def test_a_provider_that_answered_is_described_by_its_answer_not_by_the_host(self):
        """`provider_unavailable` names a failure that reached a provider. A memory
        reading on this machine does not contradict it, and letting it would hide a
        real outage behind a busy host."""
        hold = non_measurement_hold(
            _measurement(PROVIDER_UNAVAILABLE, resolution_reached=True), _host(pressure=True)
        )
        self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[PROVIDER_UNAVAILABLE])
        self.assertEqual(hold["attribution"], "route")

    def test_a_local_failure_that_reached_the_provider_is_not_reattributed(self):
        """The rule stands on its own rather than on an invariant kept elsewhere."""
        hold = non_measurement_hold(
            _measurement(EXECUTOR_LOCAL_FAILURE, resolution_reached=True), _host(pressure=True)
        )
        self.assertEqual(hold["attribution"], "route")

    def test_a_measured_attempt_is_untouched_by_any_host_reading(self):
        hold = non_measurement_hold(_measurement(MODEL_EXECUTED), _host(pressure=True))
        self.assertIsNone(hold["ttl_seconds"], "A measured route was never on hold to begin with.")
        self.assertEqual(hold["attribution"], "route")

    def test_a_silent_exit_carried_no_hold_before_and_carries_none_now(self):
        hold = non_measurement_hold(_measurement(NO_EXECUTION_SIGNAL), _host(pressure=True))
        self.assertIsNone(hold["ttl_seconds"])
        self.assertEqual(hold["attribution"], "route", "Nothing was withheld, so nothing needed excusing.")

    def test_the_signature_stays_compatible_with_callers_that_observe_no_host(self):
        hold = non_measurement_hold(_measurement(EXECUTOR_LOCAL_FAILURE))
        self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[EXECUTOR_LOCAL_FAILURE])


class RouteHoldTests(unittest.IsolatedAsyncioTestCase):
    """Whether the registry is written to at all - the observable half of attribution."""

    async def _hold(self, measurement, host):
        dispatcher = ProjectDispatcherService(None)
        with unittest.mock.patch(
            "core.ai_fleet.services.project_dispatcher.model_registry_service.record_observation",
            new_callable=unittest.mock.AsyncMock,
        ) as record:
            outcome = await dispatcher._hold_non_measured_route(
                None, "opencode/route-under-test", measurement,
                run_id="run-test", attempt_id="attempt-test", provider_propagation={}, host=host,
            )
        return outcome, record

    async def test_a_host_attributed_failure_writes_no_observation_about_the_route(self):
        outcome, record = await self._hold(_measurement(EXECUTOR_LOCAL_FAILURE), _host(pressure=True))
        record.assert_not_awaited()
        self.assertFalse(outcome["held"])
        self.assertEqual(outcome["reason"], "host_condition_not_charged_to_route")
        self.assertEqual(outcome["attribution"], "host")

    async def test_the_same_failure_on_a_calm_host_is_still_written_and_still_held(self):
        outcome, record = await self._hold(_measurement(EXECUTOR_LOCAL_FAILURE), _host(pressure=False))
        record.assert_awaited_once()
        self.assertEqual(record.await_args.kwargs["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[EXECUTOR_LOCAL_FAILURE])
        self.assertEqual(record.await_args.kwargs["state"], "unavailable")
        self.assertTrue(outcome["held"])


class DispatchPreconditionTests(unittest.IsolatedAsyncioTestCase):
    """The path that actually spends an allowance had no host check at all.

    `build_execution_preflight` is called by the run API and the readiness endpoints;
    the dispatcher calls it nowhere. So the gate could observe the host all it liked and
    the queue would still buy a dead attempt per dispatch on a machine with no room.
    """

    class _NeverCalled:
        def __getattr__(self, name):
            raise AssertionError(f"Nothing may be spent before the host is checked: {name}")

    def _dispatcher(self):
        dispatcher = ProjectDispatcherService(None)
        dispatcher.runs = self._NeverCalled()
        dispatcher.assignment = self._NeverCalled()
        dispatcher.acceptance = self._NeverCalled()
        dispatcher.context = self._NeverCalled()
        return dispatcher

    class _Session:
        def __init__(self, task):
            self._task = task

        async def get(self, model, key):
            return self._task

    def _task(self):
        return OrchestrationTaskRecord(
            id="task-host-precondition", project_id="project-host", task_type="implementation",
            title="Build", description="Build the thing", requirement_ids_json="[]",
            dependency_ids_json="[]", acceptance_json="[]", context_refs_json="[]",
            executor_needs_json="{}", state="planned",
        )

    async def test_a_host_with_no_room_stops_the_dispatch_before_anything_is_spent(self):
        exhausted = {"sufficient": False, "detail": "0.01 GB of combined memory and page file remains.", "measurable": True, "pressure": True}
        with unittest.mock.patch("core.ai_fleet.services.project_dispatcher.host_capacity", return_value=exhausted):
            with self.assertRaises(DomainError) as raised:
                await self._dispatcher()._dispatch_ai(
                    self._Session(self._task()), "task-host-precondition",
                    unittest.mock.Mock(path="/does-not-exist", id="workspace-test"), None, 60,
                )
        self.assertEqual(raised.exception.code, "host_capacity_unavailable")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(raised.exception.retryable, "The host recovers; the task is dispatched unchanged when it does.")
        self.assertIn("host", raised.exception.details)

    async def test_a_host_with_room_is_not_what_stops_a_dispatch(self):
        """The precondition refuses only the host, so it must let a workable one past -
        proven by the failure arriving from the next step rather than from this one."""
        with unittest.mock.patch("core.ai_fleet.services.project_dispatcher.host_capacity", return_value={"sufficient": True, "detail": None}):
            with self.assertRaises(AssertionError) as raised:
                await self._dispatcher()._dispatch_ai(
                    self._Session(self._task()), "task-host-precondition",
                    unittest.mock.Mock(path="/does-not-exist", id="workspace-test"), None, 60,
                )
        self.assertIn("Nothing may be spent", str(raised.exception))


class UnavailableRouteDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    """`execution_unavailable` said a queue was stuck without saying what stopped it.

    Diagnosing it meant reading the ranking back out of the database by hand, one
    dispatch at a time. The three reasons a candidate is dropped - it has no current
    capability evidence, its allowance is spent, its key was refused - are all computed
    where the error is raised, so they travel with it.
    """

    class _Result:
        def all(self):
            return []

        def scalars(self):
            return self

    class _Session:
        async def execute(self, *args, **kwargs):
            return UnavailableRouteDiagnosticsTests._Result()

        async def get(self, model, key):
            return None

    async def test_the_error_names_what_was_considered_and_why_none_of_it_ran(self):
        task = OrchestrationTaskRecord(
            id="task-diagnostics", project_id="project-host", task_type="implementation",
            title="Build", description="Build the thing", requirement_ids_json="[]",
            dependency_ids_json="[]", acceptance_json="[]", context_refs_json="[]",
            executor_needs_json="{}", state="planned",
        )
        with self.assertRaises(DomainError) as raised:
            await ProjectDispatcherService(None)._select_model(self._Session(), task)
        details = raised.exception.details
        self.assertEqual(raised.exception.code, "execution_unavailable")
        self.assertEqual(details["required_capabilities"], ["coding"])
        self.assertEqual(details["discovered_routes"], 0)
        self.assertEqual(details["candidates"], [])
        self.assertTrue(details["rejected_capabilities"], "Every legacy route was named, with what it is missing.")
        self.assertTrue(all("missing_capabilities" in item for item in details["rejected_capabilities"]))
        self.assertIn("host", details, "A stuck queue on an exhausted machine says so in the same place.")


class PreflightHostReportTests(unittest.IsolatedAsyncioTestCase):
    """The gate reports the machine, and withholds a route when the machine has no room.

    Both cases run the same executable route through the same selection; only the host
    reading differs, so the verdict flipping is attributable to it and to nothing else.
    The catalog and the system scan are stubbed for exactly that reason - read from the
    ambient database, whichever routes happened to be verified today would decide the
    answer instead of the host.
    """

    def _model(self):
        return ModelRecord(
            id="opencode/route-under-test", name="Route Under Test", provider="opencode",
            category="coding", modalities='["text"]', context_window=200000,
            is_local=False, is_free=True, is_active=True, is_reference_baseline=False,
            registry_state="verified", lifecycle_status="active", availability_state="available",
            availability_evidence="{}", source_type="external_tool", source_uri="opencode-cli",
            metadata_provenance="measured", pricing_provenance="known", capability_provenance="measured",
            pricing_currency="USD", revision=1, quality_score=80.0, speed_score=70.0,
            reliability_score=90.0, best_for='["Coding"]', not_ideal_for='[]', description="",
        )

    async def _preflight(self, host):
        model = self._model()

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        class _Session:
            async def execute(self, statement):
                entity = statement.column_descriptions[0]["entity"]
                return _Result([model] if entity is ModelRecord else [])

        class _SessionFactory:
            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *exc_info):
                return False

        scan = {
            "configured_providers": [{"provider": "opencode", "configured": True}],
            "discovered_tools": [],
            "ollama_status": {"running": False},
        }
        recommendation = {
            "task_analysis": {"category": "coding"},
            "selected_model": {"id": model.id},
            "fallback_chain": [model.id],
        }
        assessment = {"executable": True, "state": "verified", "code": "available", "detail": "Verified."}
        with unittest.mock.patch.object(readiness, "host_capacity", return_value=host), \
                unittest.mock.patch.object(readiness, "AsyncSessionLocal", _SessionFactory), \
                unittest.mock.patch.object(readiness.system_scanner, "scan_system", new=unittest.mock.AsyncMock(return_value=scan)), \
                unittest.mock.patch.object(readiness.model_router, "recommend_model", new=unittest.mock.AsyncMock(return_value=recommendation)), \
                unittest.mock.patch.object(readiness.model_registry_service, "assess", return_value=assessment):
            return await readiness.build_execution_preflight("write a function")

    async def test_a_workable_host_is_reported_and_hands_out_the_route_it_found(self):
        report = await self._preflight(
            {"sufficient": True, "detail": None, "measurable": True, "pressure": False}
        )
        self.assertTrue(report["can_execute"])
        self.assertEqual(report["execution_method"], "provider_api")
        self.assertTrue(report["host"]["sufficient"], "The machine is reported even when it is fine.")
        self.assertNotIn("host_capacity_unavailable", [item["code"] for item in report["blockers"]])

    async def test_a_host_with_no_room_withholds_the_route_under_a_blocker_of_its_own(self):
        """Before this, the machine's condition was reported as whatever route happened
        to be selected - which is how a host crash was read as route unavailability."""
        report = await self._preflight({
            "sufficient": False, "measurable": True, "pressure": True,
            "detail": "0.01 GB of combined memory and page file remains.",
        })
        blocker = next(item for item in report["blockers"] if item["code"] == "host_capacity_unavailable")
        self.assertFalse(report["can_execute"], "The same route was executable a moment ago.")
        self.assertIsNone(report["execution_method"])
        self.assertIn("page file", blocker["detail"])
        self.assertEqual(blocker["action_target"], "fleet")
        self.assertNotIn("provider_not_configured", [item["code"] for item in report["blockers"]])


if __name__ == "__main__":
    unittest.main()
