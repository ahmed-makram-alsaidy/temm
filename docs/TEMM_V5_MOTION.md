# TEMM V5 — Execution Motion + Causal Transit

**Status:** production. V5 adds motion to the truthful V4 execution model. It
introduces no execution semantics, no acceptance logic, and no backend changes.
The V4 adapter (`project-workspace-model.ts`) remains the only authority on
what is true; motion only ever asks *which observable transition occurred*.

## Motion architecture

| Piece | File | Role |
|---|---|---|
| Motion controller | `apps/web/src/components/project-workspace-motion.ts` | Pure diff of two V4 snapshots → per-task `{ transit, events, arrivedAttemptIds, settledAttemptIds }`. No timers, no state machine, no truth. |
| Sustained transit | `apps/web/src/components/visual-primitives/execution-motion.css` | The ONE sanctioned continuous motion: a dash illumination travelling the live branch (`pathLength=100`, dash 14/86, `--transit-cycle` 1200ms). Rendered only while `task.active` and inside the concurrency cap; unmounts with the state, so travel stops the moment truth stops. |
| Arrival embellishments | `project-workspace.css` (finite) + `execution-motion.css` (gate) | One-shot animations whose final frame equals the static style: attempt rung materialises (micro), attempt terminal settles (structural), live line draws on activation/retry, gate strike draws, accepted branch draws through the open gate. |
| Wiring | `ProjectWorkspace.tsx` | `useWorkspaceMotion(model)` caches the plan per model identity (unrelated re-renders never interrupt or replay an arrival), attaches `data-motion` / `data-arrived` / `data-settled`, passes `transit` to connectors and `animate` to gates. |

## Snapshot transition policy

- Production is snapshot-driven. Each authoritative refresh produces one diff;
  missed transitions are never reconstructed or queued.
- **Initial load:** `previous == null` → zero events; history settles into its
  final geometry. Only currently active truth (transit) may animate.
- **Same snapshot twice:** empty diff; transit is a stable state, not an event.
- **Hidden tab:** on `visibilitychange → visible`, the missed diffs are absorbed
  into the baseline (`settleMotionPlan` semantics) and attributes settle. CSS
  animations cannot accumulate while hidden; nothing replays.
- **Reduced motion** (`prefers-reduced-motion` or `[data-reduce-motion]`):
  the controller emits nothing and grants no transit; the CSS independently
  disables every animation and the loop outright (`--transit-cycle: 0ms` is
  not sufficient — `animation: none` is enforced). State meaning is intact
  without motion.

## Causal coverage (all driven by V4 facts)

| Transition | Motion |
|---|---|
| ready → running | live line draws in (structural), transit begins |
| attempt appears | new rung materialises (micro); prior rungs untouched |
| effect measured | effect square materialises at the gate (structural) |
| gate evaluates → accepted | segments resolve; through-line draws; green appears as a consequence |
| gate evaluates → rejected | strike draws at the closed gate; arrest is static |
| no-effect terminal | empty socket settles; nothing ever travels to a gate |
| retry | prior terminal geometry persists; new offset line draws; transit continues on the live attempt |
| run stops | transit path unmounts instantly |
| waiting / blocked / attention | still by law — no travel, no pulse |

## Concurrency

`assignTransit` grants the travelling illumination to at most 3 active tasks
(dominant first). Beyond the cap every task keeps its truthful active
treatment; only the motion aggregates. Verified at 5 concurrent tasks on
desktop and mobile.

## RTL

Transit travels the branch's resolved causal direction (the connector resolves
coordinates from the logical leading edge), so Arabic travel mirrors with the
geometry — never `scaleX`. The Closed Cell remains orientation-stable.

## Performance

No `requestAnimationFrame`, no `setInterval`, no JS animation loops in
production (static-gate enforced). Motion is CSS-only on SVG strokes; the plan
is an O(tasks × attempts) diff cached per model identity.

## Development proof

`/specimen/v5.html` — the motion lab drives the **production** model and
workspace through deterministic scenario snapshots (synthetic sequencing is
allowed only here): ready→running, sustained transit, no-effect, rejected,
accepted, full causal chain, five-active/three-transit concurrency, waiting,
blocked, plus `rtl=1`, `reduced=1`, `grey=1` variants.

```text
# from apps/web
npm run test:v5
npm run check:v5
# from the repository root
python tools_web/capture_v5_motion.py
```

The capture harness writes the frame sequence (`v5-chain-0..5`), RTL, greyscale,
mobile, reduced-motion, concurrency, waiting and blocked proofs to
`docs/specimen-v5/` and enforces per-frame invariants (transit counts, cap=3,
reduced suppression, blocked stillness, attempt-history retention, no
unverified Closed Cell, 12px floor, no overflow, document direction).

## V6 boundary

V5 animates existing acceptance truth. Criteria semantics, evidence ownership
and completeness calculation are untouched; the evidence station remains static
(chip travel between stations belongs to the later convergence slice).
