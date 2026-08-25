# TEMM V8 — Supporting Project Screens

**Status:** production. V8 extends the frozen V1–V7 language to the supporting
project surfaces — the Runs history and the Run receipt narrative — without
touching execution truth, backend contracts, or the flagship workspace.

## Before problem

- **Runs** (`Runs.tsx`) was an 8-column database grid: select, task, route,
  status pill, cost, est. avoided, duration, open. The route model ID and two
  cost columns sat at reading level; the human question ("what happened, what
  did it produce, does it need me?") had no object. Generic `status-badge`
  pills served every state with one shape.
- **RunDetails** (`RunDetails.tsx`) opened on five schema-shaped cards —
  Attempts, Measurements, Artifacts, Persisted output, Event evidence — with
  no reading order: a database inspector, not a story.
- Legacy chrome leaked 8.5–11.5px type and a violet primary button into these
  surfaces.

## Hierarchy decisions

**Run status semantics (V5–V7 law).** Earned green belongs to authoritative
acceptance/verification only. A `completed` RUN is execution completion — it
is NOT accepted, verified, gate-passed, or project-complete — so its treatment
is **neutral operational ink** (`--c-ink-1`) on both the history dot and the
narrative verdict. `RunOutcomeKind` has no accepted/verified members at the
type level, the gate forbids `--earned-green` anywhere on the Runs surfaces,
and no acceptance vocabulary exists in any run label. Clay (`--state-attention`)
marks stopped/failed runs (operational "needs you"), `--c-live` marks genuinely
running work, planned grey marks unknown states.

**Runs — the primary question: "what happened, and does it need me?"**
Each run is one history row: the prompt at title size (the human sentence the
run exists for), then one outcome line — honest label, honest sentence, when,
how long, **and the owning project's name** (resolved from one `listProjects`
call against the run's `project_id`; unknown or standalone runs show nothing
rather than an invented name). A status dot carries the operational semantics
above; the label word is never the only carrier. Route, executor, run ID,
tokens, costs with provenance, quality, and the routing decision are one
disclosure away per row (`Technical receipt`). Search and evidence comparison
are unchanged tools.

**RunDetails — the primary question: "what was asked, and what came of it?"**
Causal narrative: *What was asked* (the prompt, dominant) → verdict line →
*How it executed* (attempt list, executor identity in mono chips) → *What it
produced* (persisted output, honest absence when none) → *Measured facts*
(duration, tokens, costs with provenance notes) → *The effect on disk*
(artifact paths with 7-char checksum chips, full hash in the title tooltip) →
*Full technical receipt* (L3 disclosure: run ID, route, model/agent/workspace
IDs, token source, TTFT, value category, status reason, fallback chain, event
log). Task-run completion is never worded as acceptance or verification.

**RunWorkspace shell (real-product audit).** The completed-run page previously
opened on a fabricated 4-step recap card (which exposed the run ID at L2) and
buried the causal story below result actions and a closed L3 card. Composition
only: the recap card now renders only while a run is genuinely live; the V8
narrative leads every terminal run page; result actions and the technical
receipt follow it. No execution semantics changed.

**Readiness/setup** — unchanged in structure (contextual Attention station;
legacy onboarding stays non-auto-launching). The connect-folder sheet gains
the §17.12 boundary promise: "TEMM can only read and write inside this
folder."

**Blueprint review / requirements approval** — audited, already TEMM-native in
the flagship workspace (V3/V6): goal verbatim, requirement squares, acceptance
statements as sans prose, clarify questions inline. No change; frozen.

## Canonical data

`TaskRun` (list + detail) and `/runs/{id}/details` receipts, verbatim.
`supporting-screens-model.ts` is presentation-only: it classifies the
backend's own `status` strings into completed / stopped / running / unknown,
formats durations and costs, and projects receipts into rows. It computes no
acceptance, completion, readiness, or quality, and is gated against it
(`check:v8` forbids those vocabulary words in model code; `test:v8` asserts
completion language never claims acceptance).

## L1 / L2 / L3 mapping

| Level | Runs | RunDetails |
|---|---|---|
| L1 | prompt, outcome label + sentence, when, duration | prompt, verdict |
| L2 | search, compare selection, status dot | attempts, output, measured facts, artifacts |
| L3 | per-row Technical receipt | Full technical receipt + event log |

## Files

- `apps/web/src/components/supporting-screens-model.ts` — pure presentation.
- `apps/web/src/components/Runs.tsx`, `RunDetails.tsx` — recomposed.
- `apps/web/src/components/supporting-screens.css` — V8 styles (tokens only,
  no keyframes, 520px mobile recomposition, RTL via logical properties).
- `apps/web/src/components/Projects.tsx` — boundary-promise line only.
- `apps/web/src/__tests__/supporting-screens.test.ts` — 8 truth tests.
- `apps/web/src/specimens/V8SupportSpecimen.tsx`, `src/v8-specimen.tsx`,
  `specimen/v8.html` — dev-only verification aid rendering the real
  components with fixed receipts.
- `tools_web/check_v8_supporting_screens.py`, `tools_web/capture_v8_supporting.py`.

## Verification

```text
# from apps/web
npm run test:v8
npm run check:v8
# from the repository root
python tools_web/capture_v8_supporting.py
```

Captures (12, `docs/specimen-v8/`): Runs graphite/chalk, RunDetails
completed/failed, RTL for both, tablet for both, mobile for both + RTL mobile,
greyscale. Every shot asserts: no horizontal overflow, no `<table>`, history
rows / narrative chapters present, L3 receipt opens, document direction
matches, and no text glyph below 12px.

**Real-product proof** (`tools_web/capture_v8_product.py` →
`docs/specimen-v8/real-product-*`): boots the actual backend (`python run.py`,
:8787), drives the real UI with clicks — no query parameters, no specimen
routes: sidebar → Runs (50 live rows, project name visible on every
project-associated row at L1) → a completed run's row → RunWorkspace, where
the causal narrative leads, the verdict reads "Completed · Produced a recorded
result" in neutral ink, and the L3 technical receipt + event log open. The
harness fails on: acceptance/verified vocabulary, data tables, missing project
context, missing narrative/receipt, overflow, or a lingering recap card.

## Known limitations

1. The legacy product shell (header, sidebar, other tabs) still carries
   sub-12px type and legacy accent colours; fixing it globally was an explicit
   non-goal. V8 scopes the floor to its own surfaces (`.runs-page`,
   `.temm-v8-narrative`).
2. A failed run's receipt renders whatever the backend recorded — including a
   populated `saved_amount` estimate — verbatim. TEMM does not second-guess
   recorded financials.
3. Runs L1 shows the project **name** when the id resolves against the
   projects list; a run whose project was deleted shows no project claim
   rather than an invented one.
