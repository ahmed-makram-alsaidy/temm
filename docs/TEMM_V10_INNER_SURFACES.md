# TEMM V10 — Legacy Inner Surface Convergence

**Status:** production. V10 audits all eight legacy inner surfaces framed by
the V9 shell and converges only those whose composition materially broke the
product language. One surface received a structural change; seven received a
scoped light treatment; no backend files were touched.

## Audit classification

| Surface | Human question | Class | Treatment |
|---|---|---|---|
| System overview (Dashboard) | Is TEMM able to work? What needs attention? | **A** | Structural (bounded): task composer + quick prompts + vanity KPI row removed; readiness/attention first |
| Tools | What can TEMM execute with, and what is ready? | B | Type floor + neutral badges + ink primary |
| Settings | What can I configure? | B | Type floor + neutral badges; groups already human-purpose; Restart setup preserved |
| Insights | What did execution cost, how trustworthy are the numbers? | B | Type floor; provenance-first composition was already honest |
| Model Lab | Which model should I pick, on what measured evidence? | B | Type floor + neutral score badges + inline accent removed |
| Automation Center | What will happen and when? | B | Type floor + neutral badges; "simulated execution disabled" honesty preserved |
| Workspaces | What may TEMM touch on this computer? | B | Type floor + neutral badges; boundary framing preserved |
| Command Console | Run one command safely inside an approved folder | B (interior C) | Surrounding hierarchy + floor only; console stays mono-first by explicit exception |

## The structural change: System overview

The old Dashboard led with "What do you want to get done?" plus a free-text
composer and quick prompts — a second, weaker product competing with the
Projects flagship. V10 recomposes it as the operator surface V9 named:

1. **L1** — "System overview" + one sentence pointing real work to Projects;
   the readiness chip ("Execution route ready" / "Setup incomplete").
2. **L1** — *What needs attention*: alerts derived only from known truth
   (`workspaceCount === 0`, analytics load failure,
   `models_unavailable > 0`) via `systemOverviewModel`.
3. **L2** — Recent runs.
4. **L3/L2** — month tokens (with estimated share), estimated avoided cost,
   fleet counts.

`systemOverviewModel` classifies; it never scores. Tests prove: operational
tones only, alerts from known truth with no health/productivity/quality
scores, canonical values verbatim, and no launch/composer concept in the
model.

## The light treatment (seven surfaces)

`inner-surfaces.css`, scoped strictly to the eight page roots:

- **12px floor as a constraint**: a catch-all `!important` floor
  (`--type-200`) over every text-bearing element, with asserted hierarchy
  overrides above it (h1 at `--type-700`, page-head paragraphs at 13px,
  metric values mono at 22px). Legacy two-class rules could out-specify a
  plain floor — the floor is therefore absolute inside these pages.
- **Colour semantics**: emerald/cyan/amber badges become neutral ink chips
  (the word carries the state); attention-true badges keep clay text;
  status dots are neutral ink or clay — the glow and pulse loop are dead;
  the violet `.btn-primary` becomes TEMM ink on every treated page.
- **Console exception**: the terminal composer, output `<pre>`, and history
  stay monospace and LTR where technical; only surrounding furniture is
  treated.

## Files

- `apps/web/src/components/system-overview-model.ts` + `Dashboard.tsx` rewrite.
- `apps/web/src/components/inner-surfaces.css` (new, scoped).
- `apps/web/src/components/ModelLab.tsx` (inline accent style removed).
- `apps/web/src/App.tsx` (one import).
- `apps/web/src/__tests__/system-overview.test.ts` (4 truth tests).
- `tools_web/check_v10_inner_surfaces.py`, `tools_web/capture_v10_inner.py`.

## Verification

```text
# from apps/web
npm run test:v10
npm run check:v10
# from the repository root (real backend on :8787)
python tools_web/capture_v10_inner.py
```

Real-product walk captures (`docs/specimen-v10/`): Projects → Runs → Tools →
Workspaces → Automation → Insights → Model Lab → System overview → Settings →
Command console → back to Projects, plus RTL (overview, tools) and mobile
overview. Every shot asserts the active shell route, the page's smallest text
glyph ≥12px, no horizontal overflow, and zero green status badges/dots in the
page body.

## Remaining debt

1. Deep inner-page composition (Tools connect wizards, marketplace tables,
   settings sub-sections) keeps its legacy layout skeleton — typography,
   status semantics, and primaries are TEMM; full recomposition stays open
   for later slices if ever needed.
2. The Dashboard "Tasks today / success rate" metric was removed rather than
   redesigned; if operators miss it, it belongs to a future analytics slice
   with provenance labels.
