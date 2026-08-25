# TEMM V4 Live Task Lattice

## Purpose

V4 maps the production execution chain `task -> current run -> attempt -> workspace effect -> acceptance -> evidence` onto the static V3 project workspace. It does not add execution motion, polling, a graph library, backend behavior, or a second source of project state.

The production entry remains `apps/web/src/components/Projects.tsx`. V4 enriches each task's existing `current_run_id` with the run envelope from `GET /api/runs/{id}` and the existing attempt, event, output, artifact, usage, and latency endpoints.

## Canonical Mapping

`deriveTaskExecutionPresentation` in `project-workspace-model.ts` is the sole presentation authority for execution facts:

| Production fact | Presentation claim |
| --- | --- |
| plan task and dependency IDs | deterministic dependency order, depth, and waiting links |
| run status and current attempt ID | active run, active attempt, and concurrent active task count |
| routing mode and executor type | human-readable run summary |
| exact agent and model IDs | collapsed technical receipt only |
| run/attempt timestamps and duration | measured or recorded execution span, never an ETA |
| non-empty `workspace_diff` | measured effect |
| `no_effect === true` | no measured effect |
| neither effect fact | effect not established |
| attempt acceptance array | that attempt's gate only |
| completion task evidence | accepted task and project evidence |

An active retry never inherits an older attempt's acceptance gate. The older rejection remains visible in attempt history, while the live attempt has no gate until its own acceptance measurement exists.

The Evidence station follows the same ownership rule. It may retain the latest recorded criteria for audit, but it does not draw that older gate as the active attempt's verdict and labels the measurement as belonging to the prior attempt that reached acceptance.

## State Distinctions

- Dependency waiting remains planned work with named prerequisites; it is not executor failure.
- Executor failure is a stopped run without an acceptance rejection.
- Rejection requires a measured failed acceptance criterion.
- No effect requires the authoritative receipt flag and is independent of acceptance.
- A workspace effect does not imply acceptance.
- A completed process does not imply an accepted task.
- A passing attempt receipt does not independently promote project completion.

The task branch gate uses the active attempt's criteria while a run is live. At rest it uses the latest measured attempt or completion evidence. Green remains reserved for measured accepted evidence.

## Concurrent Work

Every live task has `active === true`. `activeTasks` and `activeCount` preserve concurrency; `currentTask` selects one dominant task only for narrative priority and primary-state composition. Secondary active tasks retain live structural treatment and are not collapsed into the dominant task.

## Dependency Trace

Hovering a task raises its direct dependency relationship without animation. The same relationship can be latched through `Trace task links`, a 44px control available in lattice and Ledger representations. The trace uses logical properties and identical causal order in LTR and RTL.

## Scale And Direction

The accepted V3 thresholds remain unchanged:

| Task count | Representation |
| --- | --- |
| 1-24 | full lattice |
| 25-80 | requirement-oriented groups |
| 81+ | Ledger |

At 820px and below the Ledger remains the readable representation for every task count. Attempt history remains folded after the newest three attempts. Group summaries now state their execution state in text as well as geometry.

## Historical Truth Limit

V4 can show every attempt for the task's current run. It cannot claim complete cross-run task history because `orchestration_tasks.current_run_id` is overwritten on a later run and `task_runs` has no orchestration-task foreign key. Run prompt, process, project, or model fields are not treated as task ownership.

The technical receipt therefore states `history current run only`. Adding authoritative cross-run task linkage is backend debt for a later execution/evidence slice, not a V4 inference or migration.

## Verification

Run from `apps/web`:

```text
npm run test:v3
npm run test:v4
npm run check:v3
npm run check:v4
npx tsc -b --pretty false
npm run lint
npm run build
```

Run from the repository root:

```text
python tools_web/check_v2_primitives.py
python tools_web/capture_v3_workspace.py
python tools_web/capture_v4_work_graph.py
```

The V4 capture matrix renders `1, 6, 24, 40, 120` tasks at `1600, 1440, 768, 375` widths in both English and Arabic. It checks scale selection, direction, horizontal overflow, state text, active task preservation, the 12px type floor, 44px trace targets, one-primary-action law, and unearned Closed Cells. Outputs are written to `docs/specimen-v4`.

## Files

- `apps/web/src/components/project-workspace-model.ts`: canonical V4 execution adapter.
- `apps/web/src/components/Projects.tsx`: current-run envelope and receipt loading with the V3 stale-project guard.
- `apps/web/src/components/ProjectWorkspace.tsx`: static run, attempt, effect, gate, dependency, and concurrency rendering.
- `apps/web/src/components/project-workspace.css`: V1-token-only V4 treatments.
- `apps/web/src/__tests__/project-execution-model.test.ts`: focused execution-truth tests.
- `apps/web/src/specimens/V4WorkGraphSpecimen.tsx`: deterministic scale and execution specimen.
- `tools_web/check_v4_work_graph.py`: static V4 contract gate.
- `tools_web/capture_v4_work_graph.py`: browser matrix and screenshot proof.
