# TEMM V7 — Deliverable Convergence + Closed Cell

**Status:** production. V7 implements the one signature moment (freeze §15):
the five-step convergence chain, the deliverable-scale Verification Seal, and
the §15.3 resting composition. It adds no execution semantics, no backend
changes, and no new truth — the chain is driven entirely by the V4 model and
the V5 motion controller.

## The chain (freeze §15.2 — five structural steps, ≤1400ms, once per project)

| Step | Window | What happens | Bound to |
|---|---|---|---|
| 1 STILLNESS | 0–180ms | Nothing moves. Transit already ceased (runs are terminal when completion is evidence-based). | inherent |
| 2 GATES RESOLVE | 180–480ms | Every accepted gate re-presents its through-line opening, head to foot, 40ms apart. | `temm-rejoin-draw` per row |
| 3 EVIDENCE CONVERGES | 480–840ms | Measured effect squares depart toward the spine (direction-aware, never mirrored) and fade; the evidence anchor materialises at the foot. | `temm-evidence-converge` |
| 4 BRANCHES RETIRE | 840–1160ms | Accepted rows fade toward their ghost weight; the lattice thins. | `temm-branch-retire` |
| 5 THE SEAL CLOSES | 1160–1400ms | The open cell at the foot closes: lower chamfers converge, the gate rule draws and takes earned green. | V2 `temm-cell-close`/`temm-gate-close`, delayed |

**Fired once per observed verification.** The V5 controller emits the single
project-level event `project-verified` only on the diff `evidence.verified:
false → true` with motion allowed. An already-verified project never replays
(initial load settles); a hidden tab absorbs the moment (settle-on-visible);
the same snapshot twice refires nothing; reduced motion never emits the event
and the CSS independently kills every chain animation. When the chain ends
(2100ms guard) the transient lattice is replaced by the resting composition —
identical to the chain's final frame, so the handover is invisible.

**Partial-project refusal:** with `completion.ready` false the event cannot
fire; the Attention station preempts instead (tested).

## Resting composition (freeze §15.3)

- The **Seal**: `ClosedCell` at **128px** (new deliverable scale 96/128 on the
  0.85 + 16/size optical curve), gate rule in earned green — the only
  saturated hue. The seal closes on **verified work with or without a
  package** (§15.4: verification and packaging are separate claims; the
  no-package case states the limitation as its own sentence).
- The **package verification mark** (`EvidencePackage`, three cells on one
  spine) appears beside the seal only when a package exists.
- The deliverable name at `--role-signature` (36px) + version.
- One measured receipt line (mono): `sha256 <7-char chip, copies full>` ·
  `N tasks verified`.
- One action (download when a ready package exists; package when verified and
  unpackaged), then one disclosure: **"What was verified ›"** — opens the
  Evidence station with its per-task micro spines (V6).
- The lattice retires into a one-line record ("N tasks proven · Show
  execution history") — the screen is left with fewer marks than before the
  chain: the reduction is the reward.

## Files

- `apps/web/src/components/project-workspace-motion.ts` — `project-verified` event.
- `apps/web/src/components/ProjectWorkspace.tsx` — convergence state, transient
  lattice (lattice-scale only), resting composition, verification disclosure.
- `apps/web/src/components/visual-primitives/` — ClosedCell 96/128.
- `apps/web/src/components/project-workspace.css` — chain choreography +
  resting styles (finite animations; V1 motion tokens; reduced-motion guards).
- `apps/web/src/__tests__/project-convergence.test.ts` — 8 truth tests.
- `tools_web/check_v7_convergence.py`, `tools_web/capture_v7_convergence.py`.

## Verification

```text
# from apps/web
npm run test:v7
npm run check:v7
# from the repository root
python tools_web/capture_v7_convergence.py
```

The capture harness proves the frame sequence (stillness → gates → converge →
retire → seal closing), the resting composition (closed 128px seal, receipt,
package mark, disclosure, retired record), RTL (the seal is orientation-stable
per §12.2), greyscale, mobile, reduced motion (resting immediately, never in
the chain state), and the unverified refusal (no seal, no chain). Outputs:
`docs/specimen-v7/`.

## Known limits

1. "Fires once per project, ever" is enforced per observed transition within
   the product's snapshot model: a reload after verification renders the
   resting composition directly (never a replay). Cross-session suppression
   would require persisting a "celebrated" flag — deferred; the visible
   behaviour already satisfies never-on-reload.
2. Step 3's evidence departure is a directional CSS translation (no pixel
   measurement, no layout thrash), reading as convergence toward the spine
   rather than literal chip flight between stations.
