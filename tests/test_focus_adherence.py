"""Defect #72: the run-focus path was stated to the executor and never checked.

TEMM computes one focus per run and renders it as `Spend this run on: X`. It then
measured only the acceptance contract, so a run that never opened X produced the same
receipt as a run that worked on X and fell short: `effect_observed` is true for both as
soon as any file changes, and the reason given for both is `acceptance_unsatisfied`.

Census over the 22 directed attempts in project-23a514f0c426 at the time of the fix:
10 touched the stated focus, 12 did not, and the three longest runs in the project's
history are all misses - 3602s with two new test files instead of the one named page,
3000s with nothing changed at all, and 1500s with only a runtime `.db` file touched.

The reading is evidence, never a gate, which is what these tests pin down: it reports,
it does not withhold, and it cannot disagree with the prompt about what was asked.
"""

import json
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.services.project_dispatcher import ProjectDispatcherService
from core.ai_fleet.storage.models import OrchestrationTaskRecord


def _task(acceptance: list[dict], description: str = "Build the thing", needs: dict | None = None) -> OrchestrationTaskRecord:
    return OrchestrationTaskRecord(
        id="task-focus",
        project_id="project-focus",
        task_type="implementation",
        title="Activity and audit history",
        description=description,
        requirement_ids_json="[]",
        dependency_ids_json="[]",
        acceptance_json=json.dumps(acceptance),
        context_refs_json="[]",
        executor_needs_json=json.dumps(needs or {}),
        state="planned",
    )


def _diff(*paths: str) -> list[dict]:
    return [{"path": path, "before": None, "after": "sha", "change": "added"} for path in paths]


class FocusAdherenceReadingTests(unittest.TestCase):
    """The four verdicts, and what each one is for."""

    def setUp(self):
        self.dispatcher = ProjectDispatcherService(None)

    def test_a_run_that_changed_every_stated_path_is_reported_as_adherent(self):
        reading = self.dispatcher._focus_adherence(
            {"stated": ["frontend/src/pages/ActivityPage.tsx"], "basis": "run_focus_directive"},
            _diff("frontend/src/pages/ActivityPage.tsx"),
        )
        self.assertEqual(reading["verdict"], "touched_all")
        self.assertEqual(reading["untouched"], [])
        self.assertEqual(reading["basis"], "run_focus_directive")

    def test_the_3602_second_run_that_wrote_tests_instead_of_the_page_reads_touched_none(self):
        """attempt-3486f5bdbae2, reproduced from its receipt.

        Its directive named exactly one path. It spent the full hour and 3.8M tokens,
        changed two files, and neither was that path - yet `effect_observed` was true
        and the recorded reason was an ordinary `acceptance_unsatisfied`. The two facts
        that distinguish this from a near-miss are the ones asserted here.
        """
        reading = self.dispatcher._focus_adherence(
            {"stated": ["frontend/src/pages/ActivityPage.tsx"], "basis": "run_focus_directive"},
            _diff("backend/src/tests/activity-history.test.ts", "frontend/src/pages/ActivityPage.test.tsx"),
        )
        self.assertEqual(reading["verdict"], "touched_none")
        self.assertEqual(reading["untouched"], ["frontend/src/pages/ActivityPage.tsx"])
        self.assertEqual(reading["changed_path_count"], 2, "The run was productive - just not on what it was asked for.")
        self.assertEqual(
            reading["changed_outside_focus"],
            ["backend/src/tests/activity-history.test.ts", "frontend/src/pages/ActivityPage.test.tsx"],
            "Where the hour actually went is named, so the miss is diagnosable and not just flagged.",
        )

    def test_partial_work_across_a_multi_path_focus_is_neither_success_nor_a_miss(self):
        reading = self.dispatcher._focus_adherence(
            {"stated": ["backend/src/routes/customers.ts", "backend/src/routes/orders.ts"], "basis": "run_focus_directive"},
            _diff("backend/src/routes/customers.ts"),
        )
        self.assertEqual(reading["verdict"], "touched_some")
        self.assertEqual(reading["touched"], ["backend/src/routes/customers.ts"])
        self.assertEqual(reading["untouched"], ["backend/src/routes/orders.ts"])

    def test_a_run_nobody_directed_is_not_charged_with_ignoring_a_direction(self):
        """`no_focus_stated` and `touched_none` must stay distinct.

        A contract with nothing outstanding emits no focus line at all. Collapsing that
        into `touched_none` would invent an instruction the run never received, which is
        the same error in miniature that this defect is about.
        """
        reading = self.dispatcher._focus_adherence(
            {"stated": [], "basis": "contract_has_no_outstanding_path"},
            _diff("frontend/src/pages/ActivityPage.tsx"),
        )
        self.assertEqual(reading["verdict"], "no_focus_stated")
        self.assertEqual(reading["basis"], "contract_has_no_outstanding_path")

    def test_a_run_that_changed_nothing_at_all_still_reports_its_stated_focus(self):
        """attempt-df279e00dbda: 3000s, zero files changed, recorded as a route timeout.

        `no_effect` deliberately excludes timed-out runs - a run that was cut off may
        have been about to write, and blaming it would blame the route for TEMM's own
        ceiling. So an empty diff on a timeout is invisible everywhere else; here it is
        a stated focus with an empty `touched`.
        """
        reading = self.dispatcher._focus_adherence(
            {"stated": ["backend/src/routes/customers.ts"], "basis": "run_focus_directive"},
            [],
        )
        self.assertEqual(reading["verdict"], "touched_none")
        self.assertEqual(reading["changed_path_count"], 0)
        self.assertEqual(reading["changed_outside_focus"], [])

    def test_a_malformed_diff_entry_cannot_break_the_reading(self):
        reading = self.dispatcher._focus_adherence(
            {"stated": ["a.ts"]},
            [{"path": "a.ts", "change": "modified"}, "not-a-dict", None],
        )
        self.assertEqual(reading["verdict"], "touched_all")
        self.assertEqual(reading["changed_path_count"], 1)

    def test_the_recorded_outside_list_is_bounded(self):
        """Receipts are persisted, so an unbounded path list is a storage defect."""
        reading = self.dispatcher._focus_adherence(
            {"stated": ["target.ts"]},
            _diff(*[f"noise/file{index:03d}.ts" for index in range(80)]),
        )
        self.assertEqual(reading["changed_path_count"], 80)
        self.assertEqual(len(reading["changed_outside_focus"]), 20)


class FocusMatchesThePromptTests(unittest.TestCase):
    """The reading is taken from the prompt's own decision, so the two cannot drift.

    This is the test that makes the evidence trustworthy. A second derivation of
    "which paths are outstanding" would be free to disagree with the sentence actually
    sent to the executor, and a receipt that confidently reports adherence to an
    instruction that was never issued is worse than no receipt at all. So these tests
    render a real prompt against a real workspace and require that what the prompt says
    and what the sink records are the same list.
    """

    def setUp(self):
        self.dispatcher = ProjectDispatcherService(None)
        self.workspace = tempfile.mkdtemp(prefix="ai-fleet-focus-")

    def _write(self, relative: str, content: str):
        path = Path(self.workspace) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _stated_in_prompt(self, prompt: str) -> list[str]:
        line = next((item for item in prompt.splitlines() if "Spend this run on: " in item), None)
        if line is None:
            return []
        return [part.strip() for part in line.split("Spend this run on: ", 1)[1].split(",")]

    def test_the_sink_records_exactly_what_the_prompt_told_the_run_to_spend_itself_on(self):
        self._write("backend/src/app.ts", "import { activitiesRouter } from './routes/activities';\napp.use('/api/activities', activitiesRouter);\n")
        task = _task([
            {"criterion_id": "activity:wiring", "evaluator": {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["activitiesRouter", "/api/activities"]}},
            {"criterion_id": "activity:screen", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/pages/ActivityPage.tsx", "contains": ["/api/activities"]}},
        ])
        sink: dict = {}
        prompt = self.dispatcher._prompt(task, self.workspace, focus_sink=sink)

        self.assertEqual(
            sink["stated"], self._stated_in_prompt(prompt),
            "The receipt would otherwise report adherence to an instruction the prompt did not give.",
        )
        self.assertEqual(sink["stated"], ["frontend/src/pages/ActivityPage.tsx"])
        self.assertEqual(sink["settled"], ["backend/src/app.ts"], "The passing path is not the run's work.")
        self.assertEqual(sink["basis"], "run_focus_directive")

    def test_a_contract_with_nothing_outstanding_states_no_focus_and_says_so(self):
        self._write("backend/src/app.ts", "app.use('/api/activities', activitiesRouter);\n")
        task = _task([
            {"criterion_id": "activity:wiring", "evaluator": {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["/api/activities"]}},
        ])
        sink: dict = {}
        prompt = self.dispatcher._prompt(task, self.workspace, focus_sink=sink)

        self.assertNotIn("Spend this run on:", prompt)
        self.assertEqual(sink["stated"], [])
        self.assertEqual(sink["basis"], "contract_has_no_outstanding_path")
        self.assertEqual(self.dispatcher._focus_adherence(sink, _diff("anything.ts"))["verdict"], "no_focus_stated")

    def test_a_certification_probe_states_no_focus_under_its_own_basis(self):
        """Probes send the bare description, so there is no directive to adhere to.

        Reported distinctly from an ordinary contract with nothing outstanding: one is a
        prompt shape that carries no focus, the other is a contract that has none.
        """
        task = _task(
            [{"criterion_id": "x", "evaluator": {"type": "path_exists_contains", "path": "missing.ts", "contains": ["z"]}}],
            description="Write a function that returns 4.",
            needs={"certification_model_id": "opencode/x-preview-f-free"},
        )
        sink: dict = {}
        prompt = self.dispatcher._prompt(task, self.workspace, focus_sink=sink)

        self.assertEqual(prompt, "Write a function that returns 4.")
        self.assertEqual(sink["stated"], [])
        self.assertEqual(sink["basis"], "certification_probe_prompt_states_no_focus")

    def test_omitting_the_sink_leaves_the_prompt_byte_identical(self):
        """The reading is an addition to the receipt, not a change to what runs.

        Every prompt TEMM has ever sent must still render the same way, or the fix
        would have silently altered the production path it exists to measure.
        """
        self._write("backend/src/app.ts", "app.use('/api/activities', activitiesRouter);\n")
        task = _task([
            {"criterion_id": "a", "evaluator": {"type": "path_exists_contains", "path": "backend/src/app.ts", "contains": ["/api/activities"]}},
            {"criterion_id": "b", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/pages/ActivityPage.tsx", "contains": ["/api/activities"]}},
        ])
        self.assertEqual(
            self.dispatcher._prompt(task, self.workspace),
            self.dispatcher._prompt(task, self.workspace, focus_sink={}),
        )

    def test_removals_are_stated_as_work_without_being_counted_as_written_paths(self):
        """A `must not exist` path is work, but honouring it means deleting it.

        Removals stay out of `stated` because that list is scored on any change, and a
        deleted path must not be read as an untouched one. They are scored instead on
        being gone - see `RemovalFocusIsCheckedTests`.

        Defect #76 corrected the assertion below. This test used to require
        `touched_all` from a run that wrote its deliverable and left the debris file in
        place, certifying as fully adherent a run that did half its directive. One of
        two directed operations was honoured, which is `touched_some`.
        """
        self._write("debris.js", "console.log('left over');\n")
        task = _task([
            {"criterion_id": "no-debris", "evaluator": {"type": "path_absent", "path": "debris.js"}},
            {"criterion_id": "screen", "evaluator": {"type": "path_exists_contains", "path": "frontend/src/pages/ActivityPage.tsx", "contains": ["/api/activities"]}},
        ])
        sink: dict = {}
        prompt = self.dispatcher._prompt(task, self.workspace, focus_sink=sink)

        self.assertIn("Spend this run on:", prompt)
        self.assertNotIn("debris.js", sink["stated"])
        reading = self.dispatcher._focus_adherence(sink, _diff("frontend/src/pages/ActivityPage.tsx"))
        self.assertEqual(reading["verdict"], "touched_some")
        self.assertEqual(reading["removals_stated"], ["debris.js"])
        self.assertEqual(reading["removals_outstanding"], ["debris.js"])
        self.assertEqual(reading["touched"], ["frontend/src/pages/ActivityPage.tsx"])


def _deleted(*paths: str) -> list[dict]:
    return [{"path": path, "before": "sha", "after": None, "change": "deleted"} for path in paths]


class RemovalFocusIsCheckedTests(unittest.TestCase):
    """Defect #76: a run directed entirely at removals was recorded as undirected.

    The verdict was computed from `stated`, which holds outstanding *writes*. A contract
    whose deliverables all pass and whose only outstanding work is deleting debris
    therefore produced `no_focus_stated` - the verdict reserved for a run nobody
    directed, and the one reading that says the finding is not about the executor -
    beside a `basis` of `run_focus_directive` in the same dict.

    attempt-30f37bfabca5 is the production case: told to spend the run removing four
    files, it spent 900s and 1.87M tokens over 60 tool calls, deleted none of them, and
    wrote eight others. Defect #47 put removals into the directive; without this half
    they were stated and never checked.
    """

    def setUp(self):
        self.dispatcher = ProjectDispatcherService(None)
        self.production_focus = {
            "stated": [],
            "removals": ["__inspect_db.cjs", "debug-db.js", "seed.js", "seed-data.js"],
            "basis": "run_focus_directive",
        }

    def test_the_production_run_that_deleted_nothing_is_no_longer_read_as_undirected(self):
        """The defect itself, on the receipt that exposed it."""
        reading = self.dispatcher._focus_adherence(
            self.production_focus,
            _diff(".gitignore", "README.md", "package.json", "scripts/build-package.js",
                  "ACCEPTANCE_SUMMARY.md", "DISTRIBUTABLE_PACKAGE.md", "PACKAGE_RELEASE_NOTES.md",
                  "TESTS_BUILD_START.md"),
        )

        self.assertEqual(reading["verdict"], "touched_none")
        self.assertEqual(reading["removals_performed"], [])
        self.assertEqual(reading["removals_outstanding"], self.production_focus["removals"])
        self.assertEqual(reading["changed_path_count"], 8)

    def test_the_verdict_never_contradicts_the_basis_recorded_beside_it(self):
        """The invariant, over every shape a focus takes.

        `basis` and `verdict` are two readings of one `focus`. If the prompt directed
        work, the verdict has to be about whether that work was done; only an undirected
        run may report `no_focus_stated`. These are the four shapes the prompt builder
        produces.
        """
        shapes = [
            ({"stated": ["a.ts"], "removals": [], "basis": "run_focus_directive"}, "writes only"),
            ({"stated": [], "removals": ["debris.js"], "basis": "run_focus_directive"}, "removals only"),
            ({"stated": ["a.ts"], "removals": ["debris.js"], "basis": "run_focus_directive"}, "both"),
            ({"stated": [], "removals": [], "basis": "contract_has_no_outstanding_path"}, "neither"),
        ]
        for focus, label in shapes:
            with self.subTest(shape=label):
                reading = self.dispatcher._focus_adherence(focus, _diff("unrelated.ts"))
                directed = focus["basis"] == "run_focus_directive"
                self.assertEqual(
                    reading["verdict"] == "no_focus_stated", not directed,
                    f"{label}: basis says directed={directed}; verdict says otherwise.",
                )

    def test_a_performed_removal_is_adherence(self):
        """The other half: doing the work reads as having done it."""
        reading = self.dispatcher._focus_adherence(self.production_focus, _deleted(*self.production_focus["removals"]))

        self.assertEqual(reading["verdict"], "touched_all")
        self.assertEqual(reading["removals_performed"], self.production_focus["removals"])
        self.assertEqual(reading["removals_outstanding"], [])

    def test_a_performed_removal_is_not_reported_as_work_outside_the_focus(self):
        """Obeying the directive must not be recorded as ignoring it.

        `changed_outside_focus` subtracted only `stated`, so a deletion - which the diff
        carries like any other change - landed in the list of paths the run touched
        instead of its focus. The reading would have accused a compliant run.
        """
        reading = self.dispatcher._focus_adherence(
            {"stated": ["a.ts"], "removals": ["debris.js"], "basis": "run_focus_directive"},
            _diff("a.ts") + _deleted("debris.js"),
        )

        self.assertEqual(reading["verdict"], "touched_all")
        self.assertEqual(reading["changed_outside_focus"], [])

    def test_rewriting_a_file_it_was_told_to_delete_is_not_adherence(self):
        """Why a removal is scored on absence and not on appearing in the diff.

        Presence in the diff is satisfied by the one outcome the criterion forbids: the
        file still existing, with new contents. Scoring that as the work being done
        would make the reading agree with a run that did the opposite of its directive.
        """
        reading = self.dispatcher._focus_adherence(
            {"stated": [], "removals": ["debris.js"], "basis": "run_focus_directive"},
            [{"path": "debris.js", "before": "old", "after": "new", "change": "modified"}],
        )

        self.assertEqual(reading["verdict"], "touched_none")
        self.assertEqual(reading["removals_outstanding"], ["debris.js"])

    def test_partial_adherence_across_a_mixed_focus(self):
        """One write done and one deletion skipped is neither success nor total miss."""
        reading = self.dispatcher._focus_adherence(
            {"stated": ["a.ts", "b.ts"], "removals": ["debris.js"], "basis": "run_focus_directive"},
            _diff("a.ts"),
        )

        self.assertEqual(reading["verdict"], "touched_some")
        self.assertEqual(reading["untouched"], ["b.ts"])
        self.assertEqual(reading["removals_outstanding"], ["debris.js"])

    def test_a_reading_taken_from_a_focus_with_no_removals_key_is_unchanged(self):
        """Older receipts and probe paths hand over a focus without the key."""
        reading = self.dispatcher._focus_adherence({"stated": ["a.ts"]}, _diff("a.ts"))

        self.assertEqual(reading["verdict"], "touched_all")
        self.assertEqual(reading["removals_stated"], [])
        self.assertEqual(reading["removals_performed"], [])
        self.assertEqual(reading["removals_outstanding"], [])


if __name__ == "__main__":
    unittest.main()
