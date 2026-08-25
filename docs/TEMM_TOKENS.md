# TEMM TOKENS — V1 Visual Foundation (Implementation Reference)

**Status: production.** The canonical semantic token layer lives at
`apps/web/src/styles/tokens.css`, imported at the top of
`apps/web/src/styles/theme.css`.

This is an implementation reference, not a brand manual. Every rule here traces
to the frozen direction (`docs/TEMM_VISUAL_EXPERIENCE_DIRECTION.md`, rev 2) and
was validated in the approved standalone proof (`D:\temm-visual-proof`).

---

## 1. What V1 established (and what it deliberately did not)

V1 is infrastructure. It defines the token API, fixes the broken foundations,
and proves the system on a dev-only specimen. It does **not** migrate existing
components, does not introduce the lattice or the Seal component, and does not
recolor any existing screen.

| Established in V1 | Deliberately deferred |
|---|---|
| Canonical semantic tokens (surfaces, ink, lines, states, motion) | Migrating legacy `--bg-*` / `--accent-*` usage onto them (per-slice) |
| 8-step type scale + semantic roles + Arabic floor resolution | Migrating the 275 legacy `font-size` declarations (V1 freeze scope, executed surface-by-surface) |
| Earned-green token API + enforcement rules | Replacing `.status-badge` variants (V1–V2 state work) |
| Mono bundled fallback (JetBrains Mono) | Seal component (V2), lattice (V4), execution motion (V5) |
| 3 undefined variables fixed; invisible button repaired | Removing `surface-card` containers (V3) |
| Dead rules removed (`health-orbit`, `quota-meter`), hover lifts removed | `mission-card::after` gradient blob (Dashboard slice) |
| Contrast gate: `tools_web/check_token_contrast.py` | Full 11-state greyscale screenshot gate (V2, needs the state primitives) |

---

## 2. Canvas mapping

The existing theme toggle selects the canvas — no new JS:

| `data-theme` | Canvas | Role |
|---|---|---|
| `'light'` (default) | **Chalk** `#f4f1ea` — warm paper | Secondary, fully supported |
| `'dark'` | **Graphite** `#12110f` — warm-neutral, **not blue-black** | Primary identity |

On Graphite, "live" is the **brightest** ink (illumination). On Chalk it
**inverts** to the **most-inked** (darkest). The grammar survives; the mechanism
flips. Both palettes pass the contrast gate on both canvases
(`tools_web/check_token_contrast.py`, run it after any token change).

## 3. Surfaces (4 levels — depth, not colour)

| Token | Level | Rule |
|---|---|---|
| `--c-canvas` | L0 | The field. Holds the spine. Never holds text directly |
| `--c-station` | L1 | Section wash. Separated by **hairline + space**, never a border box, never a shadow |
| `--c-object` | L2 | Tasks, inputs, chips. Bordered, interactive |
| `--c-overlay` | L3 | Modals/sheets. **The only level with a shadow** (`--shadow-overlay`) |

**Forbidden:** card shadows on L1/L2, new surface levels, decorative elevation.

## 4. Ink

| Token | Use |
|---|---|
| `--c-ink-1` | Primary narrative |
| `--c-ink-2` | Secondary narrative |
| `--c-ink-3` | Quiet/meta |
| `--c-ink-max` | Maximum-ink moments (Chalk press) |

Mono measurement uses the same ink scale — mono is a *family* rule (§6), not a
separate colour.

## 5. Lines and geometry

| Token | Value | Rule |
|---|---|---|
| `--c-rule` | — | Decorative hairline only; carries no state |
| `--c-line` | — | Structural lines, connectors at rest |
| `--c-line-planned` | — | Dashed planned stroke (≥3:1 non-text, both canvases) |
| `--w-hair/--w-1/--w-2/--w-3` | 1 / 1.5 / 2 / 3px | Evidence-accumulation scale. **Weight is information** — never decorative |
| `--r-chip/object/overlay/capsule` | 4 / 8 / 14 / 999px | Capsule radius is for **task capsules only** |
| `--chamfer` | 6px | 45° structural corner cut (goal cap, requirement, seal). No bezier anywhere |

**Forbidden:** radii outside the four tokens, pill-everything SaaS styling,
rounded containers around structural geometry.

## 6. Typography

Scale: 8 steps, base 15px, ratio 1.2. `--type-200` (12px) is the **absolute
floor**. Semantic roles (`--role-goal` … `--role-compact`) are the recommended
API; they alias steps so the scale stays single-sourced.

**Sans = human narrative. Mono = machine-measured fact, inline only.**

Mono is permitted ONLY for: measured values, timestamps, one-line receipts,
7-char hash chips, literal technical tokens (paths, argv), and L3 receipts.
Mono is FORBIDDEN as: table body, navigation, task/project titles, narrative
prose, headings, buttons. Practical test: squint at any L1/L2 screen — if it
reads as monospace, the rule is broken.

**Arabic / RTL (resolved in V1):**
- `[dir='rtl']` raises the two smallest steps: `--type-200` → **13px**, `--type-300` → 14px, `--type-400` → 16px. This is the empirical answer to freeze question §21.2 (validated with Alexandria in the approved proof).
- **Never set Arabic vertically** — vertical writing breaks Arabic letter joining. No decorative vertical Arabic text, ever.
- No `letter-spacing` on Arabic labels (tracking is a Latin optical device); no `text-transform` on Arabic; line-height must stay generous (≥1.55).
- Measured values inside Arabic prose stay `dir="ltr"` in mono (existing rule, preserved).
- Use logical properties (`inset-inline-start`, `border-inline-end`) in all new CSS. RTL must preserve causal/travel semantics, never mechanically mirror them.

## 7. Semantic states (the eleven)

`--state-neutral · planned · ready · running · attention · blocked · retrying · verifying · rejected · accepted · complete`

**The two-channel law:** every state must differ from every other in ≥2 of
geometry · line · fill · position. Hue is the fifth channel and **never counts**
toward the two. Consequences:

- Shared hues are intentional (attention/blocked/rejected are all `--c-clay`;
  accepted/complete are both green). Do not "fix" this with more hues —
  differentiate with geometry in V2 primitives.
- Every state hue clears ≥3:1 non-text contrast against its canvas (enforced by
  the contrast gate).
- The full greyscale screenshot gate for all eleven states lands with the V2
  state primitives.

## 8. GREEN IS EARNED (binding)

`--earned-green` / `--state-accepted` / `--state-complete` / `--mark-gate-earned`
are the **only** green tokens.

Green may appear **only** for: measured accepted evidence, verified completion,
the closed verification cell, the proven deliverable.

Green is **forbidden** for: generic success marketing, availability indicators,
primary CTAs, onboarding, active navigation, "connected" states, illustrations,
empty states, the logo. If a fact is not backed by measurement, it is not green.
When in doubt: it is not green.

## 9. Motion

| Token | Value | Tier |
|---|---|---|
| `--t-micro` | 180ms (120–220) | hover, press, chip change, leaf disclosure |
| `--t-press` | 120ms | luminance drop on press |
| `--t-struct-fast/slow` | 280 / 450ms | the system changed shape |
| `--chain-max` | 1400ms | chain ceiling; ≤6 steps, 40–80ms overlap (`--chain-overlap`) |
| `--transit-cycle` | 1200ms | sustained transit — the ONLY continuous motion; ≤3 concurrent (`--transit-max-cycles`) |

Motion is permitted **only** for (1) work in transit, (2) the direct
consequence of a user action. Everything else is forbidden. No movement exceeds
450ms in a single step. Easings: `--e-micro` (ease-out), `--e-out`
(decelerate-heavy, **no overshoot/spring**). Hover is a weight/luminance change
— **never a transform** (the `translateY` lifts were removed in V1).

**Reduced motion removes travel and preserves state** — not "disable
animation". The token layer zeroes durations and suppresses transit under
`prefers-reduced-motion` and `[data-reduce-motion='true']`; per-event
non-motion paths (e.g. "gate results render as a list") are implemented with
their events in V5.

**No lattice/execution animation exists yet** — that is V5.

## 10. Waiting / progress

Truthful waiting only. A waiting state names **what is awaited**, **why work
cannot continue**, and **whether an estimate exists** (it usually does not — say
so: "No estimate is shown because none has been measured").

**Forbidden:** fake percentages, fake ETAs, meaningless loops, skeletons that
imply measured progress, spinners. Permitted motion during a wait: sustained
transit only, and only while a run is genuinely active.

Tokens: `--c-waiting` (the sentence), `--c-waiting-note` (the no-estimate
note), `--c-waiting-track` / `--c-waiting-gap` (the line ahead of live work —
the gap is the message). Components: V2+.

## 11. Closed Cell foundation (V2 builds the component)

The Verification Seal is the **closed cell** on a 24-unit grid, 90°/45° only:

- Spine `x=12`, `y=0→24`, **overruns the cell** at both ends.
- Cell hexagon vertices `(12,4) (19,11) (19,15) (12,22) (5,15) (5,11)`.
- Gate rule `y=15`, `x=5→19`, sitting exactly on the lower chamfer line.
- **Open cell:** same geometry, bottom vertex **unjoined**, no gate rule — work
  is out, nothing claimed. **Closed cell:** verification closes the shape; the
  gate rule takes `--mark-gate-earned` (earned green).
- Optical stroke ladder (validated in the proof; a constant stroke reads chunky
  at 64px and vanishes at 16px): `--mark-weight-64/40/24/16` in grid units.
  **Below 20px the gate rule is dropped** — it collapses into the chamfer.
- Target sizes: 16 / 24 / 40 / 64 (deliverable seal 96–160 in V7).
- The seal is vertically symmetric about its own spine — **no RTL variant
  exists** (freeze §12.2, closed question).

## 12. Elevation

One shadow in the product: `--shadow-overlay`, on L3 only. `--elev-0: none` is
the default for everything else. The legacy `--shadow-sm/md/lg` still exist for
unmigrated components and are **deprecated** — do not use them in new work.

## 13. Gates and verification

- `tools_web/check_token_contrast.py` — §5.3 contrast gate, both canvases. Run after any token change.
- `npx tsc -b && npm run build` — must pass (cross-cutting gate, every slice).
- `npm run lint` (oxlint).
- Specimen: `apps/web/specimen/index.html` — dev-only proof surface (open directly in a browser; not bundled, not routed). Shows surfaces, type hierarchy, mono, states, strokes, controls, focus, RTL, reduced motion, earned vs forbidden green, greyscale toggle.

## 14. Known V1 debt (tracked for later slices)

1. Legacy `--accent` indigo (`#5b5ce2`) still drives existing components — luminance-first signalling lands as surfaces migrate (V3+).
2. 242 sub-12px `font-size` declarations in `theme.css` remain until per-surface migration (freeze assigns the sweep to V1's full scope; this slice established the scale and floor without the mass migration).
3. `.status-badge` still renders one grey shape for 9 stages / 7 task states — replaced by state primitives in V2.
4. `mission-card::after` gradient blob and remaining decorative gradients — Dashboard slice.
5. `src/index.css` / `src/App.css` are dead Vite-template files (imported by nothing, purple `#aa3bff`) — delete in V2 with the brand-collision cleanup.
6. Per-event reduced-motion behaviours (§6.5 right column) — V5 with the motion catalogue.
