# TEMM V3 Project Workspace

## Purpose

V3 replaces the Projects card stack with one continuous Spine-and-Branch composition. The surface keeps the owner's outcome dominant while showing what TEMM understood, dependency-ordered work, current attempts, measured acceptance, and delivery as one causal system.

The production entry remains `apps/web/src/components/Projects.tsx`. Existing project APIs and workflows are preserved; V3 is a presentation model and composition, not a backend redesign.

## Production Truth

The adapter in `project-workspace-model.ts` consumes:

- Project identity and the owner-written purpose.
- The current blueprint, clarification questions, and proposed requirements.
- Persisted requirements and acceptance contracts.
- Plan tasks, dependency and requirement links, orchestration state, and open needs.
- Attempt, artifact, output, and acceptance receipts for each task's `current_run_id`.
- Project completion assessment and per-task measured criteria.
- Execution readiness, workspace, and capability blockers.
- Persisted deliverable readiness, checksum, version, and download path.

The adapter does not infer accepted work from task state, output text, artifacts, or a successful process exit. A task is accepted only when completion evidence marks it done and exposes measured passing criteria. Attempt receipts can describe measured criteria and attempt outcomes, but do not independently promote project completion.

Two current backend limitations remain visible rather than fabricated:

- The Projects API loads details only for each task's current run. V3 does not claim a complete cross-run history.
- Some project needs have no project-scoped resolution endpoint. V3 shows the recorded stop without a no-op action.

## Lifecycle

The macro rail has six stations:

1. Goal
2. Blueprint
3. Requirements
4. Execution
5. Evidence
6. Deliverable

Station states are `complete`, `current`, `future`, `blocked`, and `verified`. Completed stations recede. A current station carries the strongest structural weight. An actionable execution stop breaks the path. Only a ready persisted deliverable earns the verified station treatment.

On narrower viewports the named macro rail becomes a compact logical dot rail. It preserves order without mechanically mirroring the graph for RTL.

## Work Scale

Task-count thresholds are frozen in `TASK_SCALE_THRESHOLDS`:

| Task count | Representation | Behavior |
| --- | --- | --- |
| 0-24 | Lattice | Dependency-ordered task branches, gates, and attempt geometry |
| 25-80 | Grouped | Requirement-oriented groups with the current group expanded as a ledger |
| 81+ | Ledger | Dense ordered task record |

At 820px and below, all task counts use the ledger presentation. This protects mobile and portrait-tablet readability while retaining dependency depth, current work, blockers, attempts, criteria, and technical receipts.

## Evidence Law

V3 follows the V1/V2 evidence rules:

- Green is earned only by measured accepted evidence and verified delivery.
- State is never encoded by color alone. Line treatment, gaps, gates, fill, weight, and position carry meaning.
- A completed task without measured criteria remains `verifying`, not accepted.
- A failed measured criterion produces rejected gate geometry and an attention stop.
- `completion.ready === true` establishes verified work and permits packaging.
- Download is exposed only when verified work also has a persisted deliverable with `readiness === 'ready'`.
- The Closed Cell is absent from unverified states.

The checksum is abbreviated in the primary hierarchy. The full value remains available through the copy affordance and persisted record.

## Attention

Readiness blockers, blocking project needs, rejected tasks, blocked tasks, and execution errors can preempt the normal station sequence. The attention stop presents the first useful fact and records how many additional blockers remain.

Resolution is shown only when an existing route is truthful:

- Workspace blockers open the approved-folder sheet.
- Capability blockers navigate to capability setup.
- Rejected or blocked tasks reveal their local acceptance and technical receipt.
- Open needs or generic errors without a scoped resolver expose no primary action.

While attention is active, normal stations recede to preserve one clear stop.

## Actions

`PrimaryAction` routes one visually primary action to exactly one location: outcome header, attention stop, or delivery station.

- `understand-goal`: create a blueprint from the owner goal.
- `save-clarifications`: persist confirmed owner answers.
- `approve-blueprint`: approve the proposed blueprint.
- `approve-requirements`: approve draft persisted requirements.
- `compile-plan`: compile approved requirements without starting execution.
- `connect-workspace`: open the existing workspace binding flow.
- `open-tools`: navigate to capability setup.
- `start-execution` and `continue-execution`: use the existing readiness and bounded dispatch flow.
- `review-blocker`: reveal the stopped task's acceptance evidence locally.
- `package-deliverable`: package acceptance-measured files from the primary workspace.
- `download-deliverable`: use the persisted download path.

Project switching retains the stale-response guard and clears the prior project's visible execution data before loading the next project.

## Responsive And RTL

- Desktop keeps the six-station macro rail and sticky outcome header.
- Tablet uses the compact lifecycle rail and may use the task ledger.
- Mobile stacks the outcome tools, uses 44px primary touch targets, and always uses the ledger.
- English uses Manrope, technical facts use JetBrains Mono, and Arabic uses Alexandria.
- Arabic removes Latin tracking and text transforms.
- Directional V2 primitives receive explicit `ltr` or `rtl` coordinates; CSS `scaleX` mirroring is forbidden.

## Verification

Run from `apps/web` unless noted:

```text
npm run test:v3
npm run check:v3
npx tsc -b --pretty false
npm run lint
npm run build
```

Run the V2 compatibility gate and V3 visual matrix from the repository root:

```text
python tools_web/check_v2_primitives.py
python tools_web/capture_v3_workspace.py
```

The capture harness serves `specimen/v3.html`, records Graphite and Chalk desktop states, RTL, tablet, mobile, and greyscale proofs, and fails on horizontal overflow, multiple primary actions, direction mismatch, or invalid Closed Cell claims. Outputs and `report.json` are written to `docs/specimen-v3`.

## Files

- `apps/web/src/components/project-workspace-model.ts`: pure production-data adapter.
- `apps/web/src/components/ProjectWorkspace.tsx`: flagship static composition.
- `apps/web/src/components/project-workspace.css`: V1-token-only responsive styling.
- `apps/web/src/components/Projects.tsx`: production integration and existing action handlers.
- `apps/web/src/specimens/V3WorkspaceSpecimen.tsx`: adapter-driven visual scenarios.
- `apps/web/src/v3-specimen.tsx`: specimen entry and query parsing.
- `apps/web/specimen/v3.html`: development-only Vite entry.
- `apps/web/src/__tests__/project-workspace-model.test.ts`: deterministic model contract tests.
- `tools_web/check_v3_workspace.py`: static V3 contract gate.
- `tools_web/capture_v3_workspace.py`: visual proof and viewport metrics harness.
