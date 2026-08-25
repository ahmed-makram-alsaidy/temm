# TEMM V6 — Acceptance + Evidence Experience

**Status:** production. V6 builds the acceptance and evidence experience on the
frozen V4 truth model and the V5 motion vocabulary. No execution semantics,
acceptance criteria, evidence ownership, or completeness calculation changed.
Zero backend changes.

## What V6 adds

| Piece | Where | Law |
|---|---|---|
| `MicroSpine` primitive | `visual-primitives` | The verification receipt at reading size (freeze §3.3): branch segment, measured effect, one gate, its criterion segments, rejoin stroke when accepted. Rendered **only** when criteria were measured — an unmeasured proof stays text. Direction resolves from the logical leading edge; no mirroring. The drawn segments cap at 6 for legibility while the accessible label carries the true count; the untruncated authority is the full gate in the sheet. |
| `TaskSheetView` in the adapter | `project-workspace-model.ts` | `effect` (latest attempt with an authoritative fact: non-empty `workspace_diff` → observed, `receipt.no_effect` → none, else unknown), `artifacts` (path + sha256), `microSpine` (present iff measured criteria exist). Presentation-only derivation; one canonical model. |
| Criterion evidence summaries | `CriterionView.evidence` | Only what the measured payload carries: a path stays a path, a reason stays a reason, anything unrecognised stays `measured`. Never invented detail. |
| `AcceptanceSheet` | `ProjectWorkspace.tsx` | One sheet per task (side sheet desktop, bottom sheet ≤520px): intent → measured effect (paths in mono, artifact checksums as 7-char copy chips) → the acceptance contract: full-size gate + criterion-by-criterion statements with results and measured evidence → spatial attempt history → technical receipt behind exactly one control. Accessible dialog (role, aria-modal, Escape, backdrop close). |
| Evidence stack upgrade | Evidence station | One micro spine per measured task with its effect summary; each receipt opens the task's sheet. Unmeasured work never enters the stack. |
| Blocker review | Attention action | `Review blocker evidence` now opens the stopped task's acceptance sheet — the evidence is the review. |

## Truth boundaries preserved

- FAILED EXECUTION ≠ NO EFFECT ≠ REJECTED — the sheet shows which one happened
  and why, from receipts only.
- RUN COMPLETE ≠ ACCEPTED — an attempt receipt alone never promotes the verdict;
  without the measured completion assessment the micro spine reads `evaluating`.
- ACCEPTED TASK ≠ COMPLETE PROJECT — asserted in the model tests.
- A live retry owns no verdict: its sheet states no criteria have been measured
  and draws no gate, while the older rejection stays visible in attempt history.
- No gate is ever drawn speculatively; the lattice shows no spine outside the
  sheet and the evidence stack (containment law).

## Recovery without L3

The sheet's attempt history is the recovery record: A1 no-effect (empty
socket) → A2 rejected at the gate (struck) → A3 in progress, each with its
measured facts — legible without opening the technical receipt. Verified in
`v6-sheet-recovery-1440-en.png`.

## Verification

```text
# from apps/web
npm run test:v6
npm run check:v6
# from the repository root
python tools_web/capture_v6_evidence.py
```

The capture harness proves: the accepted sheet (micro spine, criteria,
attempts, L3 receipt), the recovery sheet (3 rungs, no verdict claimed), the
at-rest rejected sheet (struck gate, checksum chip), RTL, greyscale, the mobile
bottom sheet, the evidence stack, and the lattice triggers — with invariants
for sheet state, spine presence law, 12px floor, overflow, and direction.
Outputs: `docs/specimen-v6/`.

## Known limits (recorded, not papered over)

1. Requirement-level measured criteria do not exist in the completion payload
   (requirements are credited as a count), so the freeze's "micro spine beside
   a measured requirement" has no authoritative data yet — backend debt for an
   execution/evidence slice, not a V6 inference.
2. Cross-run attempt history remains current-run-only (V4 finding unchanged).
