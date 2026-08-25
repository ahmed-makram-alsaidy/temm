"""Focused tests for StagedCapabilityTournamentService."""

import unittest
import unittest.mock
from datetime import datetime, timedelta
import json

from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ModelCapabilityEvidenceRecord, ModelRecord
from core.ai_fleet.services.execution_policy import DEFAULT_EXECUTABLE_AVAILABILITY_TTL_SECONDS
from core.ai_fleet.services.measurement import classify_measurement
from core.ai_fleet.services.executor_capabilities import ExecutorCapabilityService
from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService
from sqlalchemy import delete, select

from core.ai_fleet.services.staged_capability_tournament import (
    STAGE_DEFINITIONS,
    StagedCapabilityTournamentService,
)


class StagedCapabilityTournamentTests(unittest.TestCase):
    def test_service_exists_with_correct_methods(self):
        service = StagedCapabilityTournamentService()
        self.assertTrue(hasattr(service, "run_tournament"))
        self.assertTrue(hasattr(service, "run_command_probe"))

    def test_stage_definitions_are_valid(self):
        # Not pinned to an exact count: this test asserts every stage is
        # well-formed, and pinning the total made adding the `debugging` stage
        # fail a test that has nothing to say about how many stages there are.
        # What the tournament must actually keep true is covered by its
        # neighbours - unique ids, and coverage of every required capability.
        self.assertTrue(STAGE_DEFINITIONS)
        for stage in STAGE_DEFINITIONS:
            self.assertIn("id", stage)
            self.assertIn("title", stage)
            self.assertIn("description", stage)
            self.assertIn("acceptance", stage)
            self.assertIn("capabilities_demonstrated", stage)
            self.assertIn("setup_files", stage)
            self.assertIn("requires_prior", stage)
            # All acceptance criteria have required fields
            for criterion in stage["acceptance"]:
                self.assertIn("criterion_id", criterion)
                self.assertIn("description", criterion)
                self.assertIn("evaluator", criterion)
                self.assertIn("type", criterion["evaluator"])

    def test_stage_ids_are_unique(self):
        ids = [s["id"] for s in STAGE_DEFINITIONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_stages_cover_child_a_capabilities(self):
        """All Child A required capabilities are tested by at least one stage."""
        child_a_required = {"coding", "file_read", "file_write", "multi_file_edit", "dependency_management"}
        all_demonstrated = set()
        for stage in STAGE_DEFINITIONS:
            all_demonstrated.update(stage["capabilities_demonstrated"])
        self.assertTrue(child_a_required <= all_demonstrated,
                        f"Missing: {child_a_required - all_demonstrated}")

    def test_file_write_stage_has_no_setup(self):
        """Stage 1 creates from empty workspace."""
        stage = next(s for s in STAGE_DEFINITIONS if s["id"] == "file_write")
        self.assertEqual(stage["setup_files"], {})
        self.assertFalse(stage["requires_prior"])

    def test_file_edit_stage_requires_prior(self):
        """Stage 2 requires the proof file from stage 1."""
        stage = next(s for s in STAGE_DEFINITIONS if s["id"] == "file_edit")
        self.assertTrue(stage["requires_prior"])
        self.assertIn("temm-write-proof.txt", stage["setup_files"])

    def test_dependency_stage_has_manifest(self):
        """Stage 4 seeds a package.json with a removable dependency."""
        stage = next(s for s in STAGE_DEFINITIONS if s["id"] == "dependency_management")
        self.assertIn("package.json", stage["setup_files"])
        import json
        manifest = json.loads(stage["setup_files"]["package.json"])
        self.assertIn("remove-me", manifest["dependencies"])
        self.assertIn("keep-me", manifest["dependencies"])

    def test_passing_tournament_promotes_existing_route_with_expiring_evidence(self):
        async def exercise():
            await init_db()
            model_id = f"tournament-regression/{__import__('uuid').uuid4().hex[:8]}"
            async with AsyncSessionLocal() as session:
                session.add(ModelRecord(
                    id=model_id,
                    name="Tournament regression route",
                    provider="tournament-regression",
                    category="coding",
                    source_type="external_tool",
                    source_uri="opencode-cli",
                    availability_state="unknown",
                    revision=1,
                ))
                await session.commit()
                service = StagedCapabilityTournamentService()
                self.assertTrue(await service._promote_verified_route(session, model_id, "tournament-regression-proof"))
                model = await session.get(ModelRecord, model_id)
                self.assertEqual(model.availability_state, "available")
                self.assertGreater(model.availability_expires_at, datetime.utcnow())
                self.assertGreaterEqual(
                    (model.availability_expires_at - model.availability_checked_at).total_seconds(),
                    DEFAULT_EXECUTABLE_AVAILABILITY_TTL_SECONDS,
                )
                evidence = json.loads(model.availability_evidence)
                self.assertEqual(evidence["source"], "production_path_tournament")
                self.assertEqual(evidence["tournament_id"], "tournament-regression-proof")
                await session.delete(model)
                await session.commit()

        __import__('asyncio').run(exercise())

    def test_subset_run_renews_availability_without_minting_command_execution(self):
        """A narrowed run proves its own stages, and only its own stages.

        Renewal takes the single stage that demonstrates the coding floor. Counting
        passes against the selection alone read that as a clean sweep and certified
        command execution, which no probe in the run exercised.
        """
        async def exercise():
            await init_db()
            model_id = f"tournament-subset/{__import__('uuid').uuid4().hex[:8]}"
            dispatched = {
                "status": "running",
                "dispatched": [{
                    "task_id": "subset-task", "run_id": "subset-run", "attempt_id": "subset-attempt",
                    "status": "completed", "all_acceptance_satisfied": True, "acceptance": [], "no_effect": False,
                }],
            }

            async def stub_dispatch(_self, session, project_id, workspace_id, checkpoint_id, *args, **kwargs):
                return dispatched

            async with AsyncSessionLocal() as session:
                session.add(ModelRecord(
                    id=model_id, name="Tournament subset route", provider="tournament-subset",
                    category="coding", source_type="external_tool", source_uri="opencode-cli",
                    availability_state="unknown", revision=1,
                ))
                await session.commit()
                with unittest.mock.patch.object(ProjectDispatcherService, "dispatch_ready", stub_dispatch):
                    outcome = await StagedCapabilityTournamentService().run_tournament(
                        session, model_id, timeout_per_stage=5, stages=["file_write"],
                    )
                model = await session.get(ModelRecord, model_id)
                self.assertEqual(model.availability_state, "available", "A passing renewal must restore executability.")
                await session.delete(model)
                await session.commit()
            self.assertEqual(outcome["positive_capabilities"], ["coding", "file_read", "file_write"])
            self.assertNotIn("command_execution", outcome["capabilities_proven"])
            self.assertFalse(outcome["all_required_for_child_a"])

        __import__('asyncio').run(exercise())

    def test_exploration_trigger_persists_onto_the_probed_route_evidence(self):
        """Requirement (6) of defect #26: why a route was measured must outlive the dispatch.

        When a chronically failing route yields its renewal to bootstrap, the production
        evidence that forced the yield is recorded on the newly measured route's own
        capability evidence - so the chronic-failure-to-exploration-to-proven-route chain
        is auditable from the route it produced, not only from the volatile route_refresh
        the dispatch returned once and discarded.
        """
        async def exercise():
            await init_db()
            model_id = f"tournament-exploration/{__import__('uuid').uuid4().hex[:8]}"
            exploration = {
                "reason": "all_renewable_routes_chronically_failing_real_production_tasks",
                "yielded_route": "some-provider/chronic-coder",
                "attempts": 12, "accepted_file_writes": 1, "failed_or_unaccepted": 11,
            }
            dispatched = {
                "status": "running",
                "dispatched": [{
                    "task_id": "explore-task", "run_id": "explore-run", "attempt_id": "explore-attempt",
                    "status": "completed", "all_acceptance_satisfied": True, "acceptance": [], "no_effect": False,
                }],
            }

            async def stub_dispatch(_self, session, project_id, workspace_id, checkpoint_id, *args, **kwargs):
                return dispatched

            async with AsyncSessionLocal() as session:
                session.add(ModelRecord(
                    id=model_id, name="Tournament exploration route", provider="tournament-exploration",
                    category="coding", source_type="external_tool", source_uri="opencode-cli",
                    availability_state="unknown", revision=1,
                ))
                await session.commit()
                with unittest.mock.patch.object(ProjectDispatcherService, "dispatch_ready", stub_dispatch):
                    await StagedCapabilityTournamentService().run_tournament(
                        session, model_id, timeout_per_stage=5, stages=["file_write"], exploration=exploration,
                    )
                rows = (await session.execute(
                    select(ModelCapabilityEvidenceRecord).where(
                        ModelCapabilityEvidenceRecord.model_id == model_id,
                        ModelCapabilityEvidenceRecord.source_type == "execution",
                    )
                )).scalars().all()
                persisted = [json.loads(row.evidence or "{}").get("exploration") for row in rows]
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id))
                await session.delete(await session.get(ModelRecord, model_id))
                await session.commit()
            self.assertTrue(rows, "A passing probe writes execution evidence.")
            self.assertTrue(
                all(record == exploration for record in persisted),
                "Every execution-evidence row the probe wrote must carry the exploration record that triggered it.",
            )

        __import__('asyncio').run(exercise())

    def test_a_refused_probe_records_no_capability_evidence_at_all(self):
        """A provider that would not serve the probe measured nothing about the route.

        The tournament reads a stage it did not pass as evidence the route lacks the
        capabilities that stage demonstrates, which is what a probe is for - but a
        refused request exercised none of them. Recording it as incapacity is not
        merely wrong: renewal admits only routes whose latest execution evidence is
        positive throughout, so one refusal withdrew a proven route from renewal for
        good and the allowance returning could not bring it back. Production evidence
        2026-08-19: `aliyun/qwen3-coder-next` answered HTTP 403 `insufficient_quota`
        in 4.8s and was recorded as unable to code, read files, or write files.
        """
        async def exercise():
            await init_db()
            model_id = f"tournament-refused/{__import__('uuid').uuid4().hex[:8]}"
            refused = {
                "status": "running",
                "dispatched": [{
                    "task_id": "refused-task", "run_id": "refused-run", "attempt_id": "refused-attempt",
                    "status": "failed", "all_acceptance_satisfied": False, "acceptance": [], "no_effect": True,
                    "receipt": {"provider_refusal": {
                        "status_code": 403, "provider_code": "insufficient_quota",
                        "message": "Free quota exhausted.", "allowance_exhausted": True,
                    }},
                }],
            }

            async def stub_dispatch(_self, session, project_id, workspace_id, checkpoint_id, *args, **kwargs):
                return refused

            async with AsyncSessionLocal() as session:
                session.add(ModelRecord(
                    id=model_id, name="Tournament refused route", provider="tournament-refused",
                    category="coding", source_type="external_tool", source_uri="opencode-cli",
                    availability_state="unknown", revision=1,
                ))
                await session.commit()
                # Proven by an earlier real execution, exactly like the production
                # route this happened to. What must survive the refusal is this.
                await ExecutorCapabilityService().certify(session, model_id, {"coding": True, "file_read": True, "file_write": True}, {"run_id": "earlier-real-run"})
                with unittest.mock.patch.object(ProjectDispatcherService, "dispatch_ready", stub_dispatch):
                    outcome = await StagedCapabilityTournamentService().run_tournament(
                        session, model_id, timeout_per_stage=5, stages=["file_write"],
                    )
                evidence = (await session.execute(
                    select(ModelCapabilityEvidenceRecord).where(
                        ModelCapabilityEvidenceRecord.model_id == model_id,
                        ModelCapabilityEvidenceRecord.source_type == "execution",
                    )
                )).scalars().all()
                still_proven = await ProjectDispatcherService(None)._last_proven_by_execution(session, model_id)
                model = await session.get(ModelRecord, model_id)
                availability = model.availability_state
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id))
                await session.delete(model)
                await session.commit()
            self.assertEqual(outcome["negative_capabilities"], [], "A refusal is not a measurement of the route.")
            self.assertEqual(outcome["positive_capabilities"], [], "Nor does it prove anything.")
            self.assertTrue(outcome["stages"][0]["unmeasured"])
            self.assertEqual(outcome["stages"][0]["provider_refusal"]["status_code"], 403)
            self.assertFalse(any(not row.supported for row in evidence), "No negative execution evidence may be written from a refusal.")
            self.assertIsNotNone(still_proven, "The route must remain renewable once the allowance returns.")
            self.assertEqual(availability, "unknown", "A refused probe proves no executability either.")

        __import__('asyncio').run(exercise())


# Captured from the real CLI stream. A provider the executor cannot resolve, a
# provider name that does not exist, and a model name that does not exist all
# produce this one event - so it is the signature of "the model was never asked".
UNRESOLVED_PROVIDER_EVENT = (
    '{"type":"error","error":{"name":"UnknownError","data":'
    '{"message":"Unexpected server error. Check server logs for details.","ref":"err_2204ab86ef54"}}}'
)
# What a model that actually ran emits.
MODEL_RAN_EVENTS = (
    '{"type":"step_start"}',
    '{"type":"tool_use","part":{"tool":"read","input":{"filePath":"README.md"}}}',
    '{"type":"text","part":{"text":"I read the file but will not write anything."}}',
    '{"type":"step_finish","part":{"tokens":{"input":1204,"output":337}}}',
)


def _stdout(*lines: str):
    return [{"stream": "stdout", "content": line + "\n"} for line in lines]


def _dispatched(lines, *, satisfied: bool, effect: bool = False):
    """Build a dispatch result the way `dispatch_ready` returns one.

    The measurement is produced by the production classifier over a real event
    stream rather than asserted by hand, so these tests fail if the classifier
    stops distinguishing an unasked route from a measured one.
    """
    measurement = classify_measurement(
        lines, outcome="completed" if satisfied else "failed",
        effect_observed=effect, acceptance_satisfied=satisfied,
    )
    return {
        "status": "running",
        "dispatched": [{
            "task_id": "probe-task", "run_id": "probe-run", "attempt_id": "probe-attempt",
            "status": "completed" if satisfied else "failed",
            "all_acceptance_satisfied": satisfied, "acceptance": [], "no_effect": not effect,
            "measurement": measurement,
            "receipt": {"outcome": "completed" if satisfied else "failed", "measurement": measurement},
        }],
    }


class MeasurementGatedEvidenceTests(unittest.TestCase):
    """A probe may only write down what the route was actually asked to do."""

    def _run(self, dispatched, model_slug):
        async def exercise():
            await init_db()
            model_id = f"{model_slug}/{__import__('uuid').uuid4().hex[:8]}"

            async def stub_dispatch(_self, session, project_id, workspace_id, checkpoint_id, *args, **kwargs):
                return dispatched

            async with AsyncSessionLocal() as session:
                session.add(ModelRecord(
                    id=model_id, name="Probed route", provider=model_slug, category="coding",
                    source_type="external_tool", source_uri="opencode-cli",
                    availability_state="unknown", revision=1,
                ))
                await session.commit()
                # Proven by an earlier real execution. Whether that survives is the
                # whole question: the newest execution evidence wins aggregation.
                await ExecutorCapabilityService().certify(
                    session, model_id, {"coding": True, "file_read": True, "file_write": True},
                    {"run_id": "earlier-real-run"},
                )
                with unittest.mock.patch.object(ProjectDispatcherService, "dispatch_ready", stub_dispatch):
                    outcome = await StagedCapabilityTournamentService().run_tournament(
                        session, model_id, timeout_per_stage=5, stages=["file_write"],
                    )
                negative = (await session.execute(
                    select(ModelCapabilityEvidenceRecord).where(
                        ModelCapabilityEvidenceRecord.model_id == model_id,
                        ModelCapabilityEvidenceRecord.source_type == "execution",
                        ModelCapabilityEvidenceRecord.supported.is_(False),
                    )
                )).scalars().all()
                negative_rows = sorted(row.capability for row in negative)
                still_proven = await ProjectDispatcherService(None)._last_proven_by_execution(session, model_id)
                await session.execute(delete(ModelCapabilityEvidenceRecord).where(ModelCapabilityEvidenceRecord.model_id == model_id))
                await session.delete(await session.get(ModelRecord, model_id))
                await session.commit()
            return outcome, negative_rows, still_proven

        return __import__("asyncio").run(exercise())

    def test_a_probe_whose_provider_never_resolved_records_no_capability_evidence(self):
        """Production evidence 2026-08-20, `run-133922d95108` / `attempt-2204ab86ef54`.

        Exit 1 after 1931ms, empty diff, no stderr, one opaque stdout event, the
        provider declared only in a config the isolated stage workspace could not
        see. TEMM recorded that the route could not code, could not read files and
        could not write them - three verdicts about a request that never left the
        machine, each of which outranked what an earlier real execution had proven.
        """
        outcome, negative_rows, still_proven = self._run(
            _dispatched(_stdout(UNRESOLVED_PROVIDER_EVENT), satisfied=False),
            "tournament-unresolved",
        )
        stage = outcome["stages"][0]
        self.assertEqual(outcome["negative_capabilities"], [], "A request that was never sent measured nothing.")
        self.assertEqual(outcome["positive_capabilities"], [], "Nor did it prove anything.")
        self.assertTrue(stage["unmeasured"])
        self.assertEqual(stage["measurement_classification"], "executor_local_failure")
        self.assertEqual(stage["measurement_reason"], "local_resolution_failed")
        self.assertFalse(stage["measurement"]["resolution_reached"])
        self.assertEqual(stage["measurement"]["error_events"][0]["ref"], "err_2204ab86ef54", "The stage has to keep enough to explain itself.")
        self.assertEqual(negative_rows, [], "No negative execution evidence may be written from a non-measurement.")
        self.assertIsNotNone(still_proven, "What an earlier real execution proved must survive a probe that never ran.")

    def test_a_probe_the_model_answered_and_failed_records_incapacity(self):
        """The one case a probe exists to record, and it must still work.

        The model resolved, ran, spent tokens, read a file, answered in text, and
        left the contracted file unwritten. That is a measurement of the route, and
        withholding it would make the tournament unable to conclude anything at all.
        """
        stage_definition = next(item for item in STAGE_DEFINITIONS if item["id"] == "file_write")
        outcome, negative_rows, _ = self._run(
            _dispatched(_stdout(*MODEL_RAN_EVENTS), satisfied=False),
            "tournament-ran-and-failed",
        )
        stage = outcome["stages"][0]
        self.assertEqual(outcome["negative_capabilities"], sorted(stage_definition["capabilities_demonstrated"]))
        self.assertEqual(negative_rows, sorted(stage_definition["capabilities_demonstrated"]), "Measured incapacity is written down.")
        self.assertNotIn("unmeasured", stage)
        self.assertEqual(stage["measurement"]["classification"], "model_executed")
        self.assertIn("text", stage["measurement"]["execution_proof"])

    def test_a_probe_the_model_answered_and_passed_records_capability(self):
        outcome, negative_rows, still_proven = self._run(
            _dispatched(_stdout(*MODEL_RAN_EVENTS), satisfied=True, effect=True),
            "tournament-ran-and-passed",
        )
        stage_definition = next(item for item in STAGE_DEFINITIONS if item["id"] == "file_write")
        stage = outcome["stages"][0]
        self.assertEqual(outcome["positive_capabilities"], sorted(stage_definition["capabilities_demonstrated"]))
        self.assertEqual(negative_rows, [])
        self.assertTrue(stage["passed"])
        self.assertNotIn("unmeasured", stage)
        self.assertIsNotNone(still_proven)


if __name__ == "__main__":
    unittest.main()
