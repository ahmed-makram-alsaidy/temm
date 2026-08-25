# TEMM VISUAL SYSTEM — DESIGN FREEZE

**Status: FROZEN for implementation.** Revision 2, 2026-08-23.
Creative direction approved in principle at revision 1; this revision applies the twelve
approved corrections and closes the design.

**No code was written or modified to produce this document.** The working tree was not reset,
cleaned, stashed, committed or pushed.

Baseline: Slice 1 + Slice 2 closed and green, 849 passed / 0 failed. Real production chain
proven — Project → Workspace → Readiness → Dispatch → Run → Attempt → Filesystem Effect →
Acceptance → Completion → Deliverable. Antigravity proven as a production executor. CLI/SDK
explicit-goal compatibility closed.

Core direction, preserved unchanged:

> **THE SPINE AND THE BRANCH**
> **ORCHESTRATION MADE VISIBLE**
> **COMPLEXITY → COORDINATION → VERIFIED CLARITY**

---

## CONTENTS

| § | Section | Status in this revision |
|---|---|---|
| 0 | Measured baseline | Preserved |
| 1 | Visual thesis | Preserved, tightened |
| 2 | The metaphor — Spine and Branch | Preserved, not replaced |
| 3 | **Three scales of the Spine** | **New — correction 1** |
| 4 | Node and connection grammar | Revised (Rejected added) |
| 5 | **Semantic state law — 11 states** | **New/complete — correction 2** |
| 6 | **Motion tiers** | **Rewritten — correction 3** |
| 7 | **The TEMM Verification Seal** | **New — correction 4** |
| 8 | **Typography law and guardrails** | **Revised — correction 5** |
| 9 | Design tokens | Preserved, aligned to §5/§8 |
| 10 | Work graph — progressive disclosure | Preserved |
| 11 | **Responsive and density matrix** | **New — correction 6** |
| 12 | **RTL direction law** | **Formalised — correction 7** |
| 13 | **Flagship Project Workspace** | **New, high detail — correction 8** |
| 14 | **First live execution moment** | **New — correction 9** |
| 15 | **Deliverable convergence** | **Rewritten — correction 10** |
| 16 | Execution and recovery visualization | Preserved |
| 17 | Key screen art direction | Preserved, condensed |
| 18 | First 30 seconds | Aligned to §7 seal + §6 tiers |
| 19 | **Removal contract / Preserve contract** | **Formalised — correction 11** |
| 20 | **Implementation freeze order** | **Rewritten — correction 12** |
| 21 | Unresolved creative questions | New |

---

## 0. MEASURED BASELINE

Every claim in this document is anchored to measurements taken from `apps/web` in this
repository. These numbers are the mechanical reason the product looks less capable than it is,
and they are the acceptance baseline the implementation must beat.

| Measurement | Value | Consequence |
|---|---|---|
| `font-size` declarations in `src/styles/theme.css` | 275 | — |
| …under 10px | **207 (75%)** | Nothing can be dominant when almost everything is 8px |
| …under 12px | **242 (88%)** | — |
| …16px or larger | **11 (4%)** | The product has almost no voice |
| Distinct font sizes in use | **28**, 6.5px → 28px | 6.5 / 6.8 / 7 / 7.2 / 7.5 / 7.8 / 8 / 8.5 / 8.8 / 9 / 9.5 / 10 / 10.5 / 11 / 11.5 / 12 / 12.5 / 13 … no ratio, no scale |
| Type tokens (`--text-xs/sm/md/lg`) used | **1 time total** | The token layer is decorative |
| Spacing token uses vs hardcoded px | **29 vs 484** | No rhythm exists |
| Radius token uses vs hardcoded | **8 vs 147**, across **17 distinct radii** (3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,20,22,999) | No shape language exists |
| CSS variables used but **never defined** | **3** — `--bg-card`, `--border`, `--bg-elevated` | `theme.css:144` gives the sidebar's primary "New project" button a transparent background and an invisible border |
| `.status-badge` variants styled | **1** (`.completed`, `theme.css:1380`) | 9 project stages and 7 task states render as the same grey pill |
| Structural classes on the flagship Projects screen with **no CSS rule at all** | **~12** — `project-spine-workspace`, `project-progress`, `spine-next-action`, `spine-section`, `blueprint-requirements`, `spine-review-action`, `task-progress-list`, `task-progress-head`, `task-blocker`, `deliverable-row`, `readiness-blockers`, `project-readiness-card`, `project-workspace-setup` | The most valuable screen in the product is substantially unstyled |
| `@keyframes` in the entire product | **2** (`pulse`, `spin`) | There is no motion system |
| Graph / chart / animation libraries | **0** | No `recharts`, `d3`, `reactflow`, `cytoscape`, `dagre`, `mermaid`, `framer-motion` |
| Authored `<svg>` / `<canvas>` in TSX | **0** | All 15 `svg` selectors in CSS merely recolor lucide icons |
| Visualizations of task graph / dependencies / parallelism | **0** | `edges` is read only for `.length`, printed as the string `"N nodes · M edges"` (`AutomationCenter.tsx:99`) |
| Dead visual code | `.health-orbit` conic ring (`theme.css:261`), `.quota-meter` (`theme.css:1424`) — zero TSX references | Someone already wanted a gauge; it never landed |
| Top-level nav surfaces / addressable sub-views | **10 / ~35** | Run history ×4, run evidence ×3, workspace picker ×4, leaderboard ×2, skills ×2, baseline model ×3 |
| `<pre>` blocks / un-collapsed by default | **9 / 6** | — |
| Full 64-char SHA-256 in the **default** view | **2** (`FleetManager.tsx:275`, `Projects.tsx:260`) | — |
| Raw DB enums rendered as body copy | **~18** | `lifecycle_status`, `auth_state`, `auth_method`, `health_state`, `registry_state`, `availability_state`, `cost_provenance`, `metadata_provenance`, `pricing_provenance`, `capability_provenance`, `score_provenance`, `discovery_state`, `discovery_source`, `event_type`, `executor_type`, `permission_profile`, `tool_kind`, `protocol_version` |

**Diagnosis, one sentence:** TEMM's interface is a well-organised database browser in a
light-grey SaaS skin, and the screen carrying the entire product thesis is the least finished
screen in the app. The system's single greatest achievement — that it refuses to lie about
completion — has **zero** visual representation.

---

## 1. VISUAL THESIS

> **TEMM does not claim. TEMM shows.**
> The interface is instrumentation, not decoration. Every element on screen is either
> **evidence**, or the **path to evidence**.

**Law 1 — Proof is the most beautiful thing on the screen.** Competitors make the *promise*
beautiful: the gradient, the sparkle, the thinking shimmer. TEMM inverts it. The promise is
plain text; the **measured fact** gets the weight, the light and the finish. A passing acceptance
criterion is the most satisfying visual event in the product.

**Law 2 — The visual rule is the engineering rule.** TEMM's law is that nothing completes
without typed acceptance evidence. The visual system must therefore make an unproven claim
*structurally unable to occupy the position of a proven one*. Not styled differently —
**positioned differently.** Where a competitor's UI *could* be lying, TEMM's UI is geometrically
incapable of it.

**Law 3 — The end state is simpler than the start state.** COMPLEXITY → COORDINATION → VERIFIED
CLARITY is not a caption; it is a literal reduction in the number of marks on screen. A project
begins as many thin uncertain lines and ends as one thick certain line and a seal.

Rejected outright: gradient hero blobs, glowing orbs, glassmorphism, cyberpunk, neon, 3D
spheres, AI shimmer, particle fields, ambient loops, template SaaS card grids, and any animation
that does not carry information.

**Reference class: precision instruments.** Glass cockpit PFDs, oscilloscope traces, Swiss rail
signage, engineering drawings, Braun. Not SaaS. Not developer tools. Not AI products.

---

## 2. THE METAPHOR — THE SPINE AND THE BRANCH

*Preserved from revision 1. Not replaced.*

A single **SPINE** carries the project: the load-bearing line of *verified* progress.
Work leaves the spine as a **BRANCH**. And the one rule that defines TEMM:

> **A branch cannot rejoin the spine without measured acceptance evidence.**

That is not a metaphor *for* the engineering law. It **is** the engineering law, drawn. A user
who reads the picture understands why TEMM refused to mark a task complete without reading a
word of explanation.

| Brief requirement | How the metaphor answers it |
|---|---|
| Work **enters** | The spine begins at a solid cap carrying the user's verbatim goal |
| Work **decomposes** | Branches leave the spine |
| Work **branches** | A failed attempt spawns a parallel offset segment; both stay visible |
| Work **gets routed** | A capability glyph docks at the branch tip — capability, never brand |
| Work **executes** | Illumination travels the branch segment toward the gate |
| Work **gets verified** | The branch must pass a gate whose segments light one per typed criterion |
| Work **converges** | The branch merges back; the spine steps up one weight |
| **Outcome** | The spine terminates in the Verification Seal (§7) |

**Why not a chatbot, a canvas, or a Kanban.** A transcript makes the *model* the protagonist. A
node canvas makes the *graph* the protagonist. A board makes the *ticket* the protagonist. The
spine makes the **verified outcome** the protagonist and demotes runs, attempts, routes and
executors to what they actually are — mechanics of getting a branch back to the spine.

It is also vocabulary the codebase already earned: `Projects.tsx` ships
`project-spine-workspace`, `spine-next-action`, `spine-section` and the eyebrow `PROJECT SPINE`
(`Projects.tsx:254`). This direction finishes a metaphor that was started and never given form.

---

## 3. THREE SCALES OF THE SPINE

**Correction 1.** The metaphor's greatest risk is becoming a repeated visual gimmick — a spine
decoratively drawn on every surface until it means nothing. The defence is a strict scale
system. There are exactly **three** scales, each with a different job, a different density, and
a hard rule about when it must **not** appear.

### 3.1 MACRO SPINE — the project lifecycle

**Job.** Answer *"where is this project?"* in under one second.

**Content.** Exactly six stations, always the same six, always in this order:

```
  ▪  GOAL            the owner's words, verbatim
  │
  ◫  BLUEPRINT       what TEMM understood
  │
  ◨  REQUIREMENTS    the typed contracts
  │
  ═  EXECUTION       the work (opens into the MESO spine)
  │
  ▤  EVIDENCE        what was measured
  │
  ⬢  DELIVERABLE     the Verification Seal
```

**Density.** Six nodes maximum. No branches. No attempts. No gates. It is a *rail*, not a graph.

**Weight.** The macro spine's weight expresses *lifecycle progress*, not evidence count:
hairline before the blueprint, mid-weight through execution, full weight when the deliverable
seals.

**Where it appears.**
- The **leading rail of the Project Workspace**, full height, always visible (§13).
- The **project row in the Projects list**, as a 24px horizontal micro-rail — same six stations,
  same order, rotated. This is the only place the spine is drawn horizontally, and it is drawn
  horizontally *because* rotating it prevents it from being confused with the interactive
  workspace spine.
- The **Today view**, one per active project.

**Where it must NOT appear.** Settings. Tools/Fleet. Console. Any surface that is not a project.
A spine outside a project lifecycle is decoration and is forbidden.

### 3.2 MESO SPINE — the work graph

**Job.** Answer *"what is planned, running, blocked, retrying, finished — and what depends on
what?"*

**Content.** The lattice. Branches leaving the spine, tasks as capsules, attempts as segments,
gates as slots, effects as filled squares, dependency depth mapped to vertical position.

**Density.** Governed by the §11 matrix. Full lattice ≤24 tasks; grouped 25–80; Ledger above 80.

**Where it appears.** Inside the **EXECUTION station of the macro spine, and nowhere else.** The
meso spine is a *zoom into one station*, not a separate screen. This containment is what stops
the metaphor multiplying: there is one lattice per project, in one place.

**Where it must NOT appear.** Any project before its plan is compiled. Any list view. Any
overview. The Today view. A lattice with no tasks in it is not an empty state — it is an absence,
and the correct rendering is one sentence of text.

### 3.3 MICRO SPINE — the verification receipt

**Job.** Answer *"was this proven, and by what?"*

**Content.** A single branch segment, one gate, and its criterion segments — one task's proof, in
isolation. Roughly 120×64 units. It is the acceptance gate at reading size.

```
      ▪ effect measured
   ───┤
      ├─┬─┬─┐
    ══╡ │ │ ╞══   ← three typed criteria, three segments
      └─┴─┴─┘
   ═══════════▶   ← accepted, gate open, rejoining
```

**Where it appears.**
- The **task detail sheet** header — the proof of that one task.
- Inline beside a **requirement**, once its acceptance has been measured.
- The **deliverable evidence stack**, one micro spine per accepted task.
- The **package verification mark** on an exported artefact.

**Where it must NOT appear.** Anywhere the criteria are not yet measured. An unmeasured micro
spine is a claim, and claims are text, not geometry. **A gate is never drawn speculatively.**

### 3.4 The containment law

> **Macro contains Meso contains Micro. A scale may never appear outside its parent scale, and
> no scale may appear twice on one screen.**

One project workspace therefore shows: one macro spine (the rail), one meso spine (inside the
execution station), and micro spines only inside task sheets and the evidence stack. Three
scales, three jobs, zero repetition. Every other surface in the product shows **no spine at
all** — which is what keeps it meaning something when it does appear.

---

## 4. NODE AND CONNECTION GRAMMAR

### 4.1 Node types — seven, not more

| Node | Geometry | Rule |
|---|---|---|
| **Goal cap** | Filled square, flat top, 45° chamfered bottom corners | Carries the owner's words verbatim. Never paraphrased, never truncated in the primary view |
| **Requirement** | Small square with a notch cut from one edge — a contract, a key | The notch **is** the acceptance contract. A requirement with no typed evaluator draws with **no notch** and is visibly a weaker object |
| **Task** | Capsule (stadium) on a branch | Fixed width; only weight, fill and state change |
| **Effect** | Small filled square appearing *on* the branch | The only object that can feed a gate. A branch with no effect square **physically cannot reach** the gate |
| **Gate** | Horizontal slot across the branch, divided into N segments — one per typed criterion | Opens only when every segment passes. The product's central visual event |
| **Route glyph** | Small chevron notch docking at the branch tip | Labelled by **capability**, never by brand |
| **Seal** | The Verification Seal (§7) | Draws only when completion is evidence-based. There is no provisional seal |

**Deliberately not nodes:**

- **A Run is not a node. A run is a length of line.** Making runs nodes is exactly how the
  current UI became a database browser (`RunDetails.tsx`, `Runs.tsx`'s 8-column grid). A run is a
  *stretch of travel between a task and its gate*: it has length (duration), weight (evidence
  produced) and continuity (whether it arrived). It does not have a card.
- **An Attempt is not a node.** An attempt is a **tick** on the segment. Attempt 2 is a
  **parallel offset segment**; attempt 1 desaturates but does not disappear.
- **A model/provider is not a node.** It is at most a capability label, and at L3 a receipt line.

### 4.2 Connection grammar — meaning without colour

| Line | Meaning |
|---|---|
| Dashed hairline | Planned — not yet measured |
| Solid hairline | Ready — measured to exist, not yet productive |
| Solid + travelling illumination | Running — real work in transit |
| Solid, terminating in a **gap before** the gate | Blocked — never arrived. *The gap is the message* |
| Solid, terminating **flush against a closed** gate | Rejected — arrived, was measured, was refused |
| Two parallel offset segments | Retrying — original desaturated, new one live |
| Solid, full weight, continuous **through** the gate | Accepted |
| **Line weight** | Accumulated evidence. The spine steps up one weight per accepted task |

The Blocked/Rejected distinction is the most important geometric decision in the grammar and is
new in this revision. *Blocked* never reached the gate. *Rejected* reached it, was measured, and
did not satisfy the contract. Those are entirely different facts about TEMM's behaviour and they
must not look alike.

**Geometry is orthogonal with 45° chamfers only.** No bezier curves. Bezier node graphs are the
universal signature of AI / n8n / Zapier, and TEMM is not that. Rail-schematic geometry reads as
engineering and infrastructure, renders cheaply, and mirrors cleanly under RTL.

---

## 5. SEMANTIC STATE LAW — ELEVEN STATES

**Correction 2.** Eleven states, fully specified. Two laws govern them.

> **THE COLOUR LAW — GREEN IS EARNED.**
> Green appears in TEMM **if and only if** something was measured and accepted.
> Forbidden without exception: empty states, onboarding, marketing chrome, availability badges,
> provider status, buttons, links, illustrations, the logo, and any "connected" indicator that is
> not evidence-backed.

> **THE TWO-CHANNEL LAW.**
> Every state must differ from every other state in **at least two** of four channels:
> **geometry · line · fill · position.** Colour is a fifth channel and never counts toward the
> two. Consequence: the entire product is legible in greyscale, and no state is knowable by hue
> alone.

### 5.1 The state table

Hue names are semantic tokens, not final values. Fill percentages are of the state's own ink.

| State | Geometry (channel 1) | Line (channel 2) | Fill (channel 3) | Position (channel 4) | Hue | Label (always present) |
|---|---|---|---|---|---|---|
| **Neutral** | Capsule, plain | Solid hairline | None (0%) | On spine | Ink secondary | — |
| **Planning** | Capsule, plain | **Dashed** hairline | None | Off-spine, branch **not yet drawn to gate** | Ink tertiary | "Planned" |
| **Ready** | Capsule + **tip cap** | Solid hairline | None | Branch drawn, **short of gate** | Ink primary | "Ready" |
| **Running** | Capsule + tip cap + **route glyph** | Solid + **travelling illumination** | None | In transit toward gate | **Warm illumination** | "Running" |
| **Needs attention** | Capsule + **notch removed** (a bite out of the leading edge) | Solid + **gap** | **Hatched 25%** | Branch stops, **promoted to Attention station** | **Clay** | The decision required, stated plainly |
| **Blocked** | Capsule, plain | Solid + **gap before gate**, no transit | Hatched 25% | **Gap before** gate | Clay | "Blocked" + the dependency or blocker |
| **Retrying** | Capsule + route glyph | **Two parallel offset segments**, transit on the new one | None on new; **35% ghost** on old | Both segments present | Warm illumination | "Retrying — attempt N" |
| **Verifying** | Capsule + **gate segments lighting** | Solid; illumination travels **across** the gate, not along the branch | None | At the gate | **Cool illumination (steel)** | "Checking acceptance evidence" |
| **Rejected** | Capsule + **gate closed, ≥1 segment struck** (a diagonal through the failed segment) | Solid, **flush against closed gate** | **Solid 100% on the failed segment only** | **Flush at** gate, not through | Clay | "Not accepted" + which criterion failed |
| **Accepted** | Capsule + **gate open** | Solid **full weight through** the gate | **Solid 100%** | **Through** the gate, rejoining | **Verified green** | "Accepted — measured" |
| **Complete** | Capsule + **weight step on spine** | Full weight, merged | Solid 100% | **On spine**, load-bearing | Verified green | "Complete" |

### 5.2 Why each pair is distinguishable in greyscale

The two-channel law is testable. Spot checks on the pairs most likely to collide:

- **Blocked vs Needs attention** — both clay. Differ by *geometry* (notch removed) and *position*
  (Needs attention is promoted to the Attention station and owns the viewport; Blocked stays in
  the lattice).
- **Blocked vs Rejected** — both clay. Differ by *position* (gap before gate vs flush at gate)
  and *geometry* (closed gate with a struck segment).
- **Rejected vs Accepted** — differ by *geometry* (gate closed + struck vs gate open), *position*
  (flush vs through) and *line* (arrested vs full-weight continuous). Three channels; the most
  consequential distinction in the product carries the most redundancy.
- **Running vs Verifying** — differ by *illumination axis*: along the branch vs across the gate.
  Direction of travel is a channel, and it is legible with hue removed.
- **Accepted vs Complete** — differ by *position* (through the gate vs merged onto the spine) and
  by the spine's *weight step*. Accepted is a task fact; Complete is a spine fact.
- **Planning vs Ready** — differ by *line* (dashed vs solid) and *geometry* (tip cap).

### 5.3 Contrast requirements

Binding on both Graphite (dark, primary) and Chalk (light, secondary).

| Element | Requirement | Basis |
|---|---|---|
| Body text (`--type-400`+) | **≥ 4.5:1** | WCAG 2.1 AA 1.4.3 |
| Small text (`--type-200/300`) | **≥ 4.5:1** — no large-text exemption is claimed anywhere in TEMM | 1.4.3, deliberately strict |
| Lattice strokes, node borders, gate segments, state indicators | **≥ 3:1** against their adjacent surface | WCAG 2.1 AA 1.4.11 non-text contrast |
| Focus ring | **≥ 3:1** against both the component and the surface behind it | 1.4.11 |
| Hairline separators (decorative only, carrying no state) | Exempt | Not informational |
| Any two semantic states, adjacent | **≥ 3:1** from each other, **and** distinguishable with hue removed | Two-channel law |
| Verified green on Graphite | **≥ 4.5:1** even as a graphical fill | It is the product's payoff; it must never be marginal |

**Verification gate for §5:** a greyscale screenshot of every state, at 100% and 25% zoom, in
which all eleven remain distinguishable. If a screenshot fails, the state design is wrong — not
the screenshot.

---

## 6. MOTION TIERS

**Correction 3.** The revision-1 universal ≤200ms rule is withdrawn. It was too blunt: it made
structural events (a branch forming, a gate evaluating, evidence converging) either impossible
or visually indistinguishable from a hover.

### 6.1 The motion law, restated

> **Motion in TEMM is permitted for exactly two reasons:**
> **1. Work is in transit.**
> **2. The user just acted, and this is its consequence.**
> **Anything that is neither is forbidden.**

### 6.2 The two tiers

**MICRO MOTION — 120–220ms.** Local response. Confirms an interaction; carries no structural
meaning.
- hover, press, release
- state chip change
- small confirmation
- disclosure expand/collapse of a leaf
- focus move, selection
- input validation response
- Easing: standard ease-out. Interruptible: **always**. Never queued, never chained.

**STRUCTURAL MOTION — 280–450ms.** The system changed shape. Carries meaning; the movement *is*
the information.
- branch creation
- task state transition
- attempt branching
- gate evaluation (per criterion)
- evidence convergence
- deliverable assembly
- station collapse when a stage settles
- Easing: decelerate-heavy, no overshoot, no bounce, no spring. Interruptible: **always** —
  interrupting settles the animation to its end state immediately, never reverses it.

**Nothing may exceed 450ms in a single movement.** There is no third tier for long animation.

### 6.3 Chaining, and the anti-cinematic cap

Some events are genuinely multi-step (deliverable convergence, the first-execution sequence). They
are expressed as **chains of structural steps**, never as one long move.

> **CHAIN LAW.** A chain is a sequence of structural steps, each **280–450ms**, overlapping by
> **40–80ms**. **A chain may not exceed 1400ms total, and no chain may contain more than 6
> steps.** A chain runs **once per real system event** and is never replayed on re-render,
> re-mount, tab focus, or navigation return.

This is what keeps the product from becoming cinematic: the *unit* of motion stays at human
reaction scale, and only genuinely compound events read as compound.

### 6.4 Sustained indication — not a tier

**Transit** is not a transition and therefore not in the tier system. It is a **sustained state
indicator**: a single illumination travelling a branch segment on a **1200ms cycle**, present
**only while a run is genuinely active**, and stopping **instantly** — not fading — the moment the
run reaches a terminal state.

Constraints on sustained indication, which exists exactly once in the product:
- One element per active run. Never more than **3 concurrent** transits on screen; beyond three,
  the lattice shows a single aggregate transit on the spine and a count.
- No sustained motion anywhere else: no ambient loops, no breathing gradients, no shimmer, no
  skeleton wave, no pulsing dots, no spinning refresh icons.
- Consequence: **if something is moving in TEMM, real work is happening.** Motion becomes
  diagnostic and the product's pulse is readable from across a room.

### 6.5 Structural animation catalogue with reduced-motion behaviour

Reduced motion **removes travel and preserves state.** It is not "disable animation" — every row
below has a non-motion path that carries the same information. Nothing in TEMM is knowable only
by watching.

| # | Structural event | What it communicates | ms | Movement | Reduced-motion behaviour |
|---|---|---|---|---|---|
| 1 | Goal accepted | Your words are now the contract | 320 | Typed text settles into the goal cap; spine draws down one station | Cap and spine render in final position; goal text renders in place |
| 2 | Understanding begins | TEMM is reading, not generating | sustained, 1200ms cycle | One reading indicator traverses the goal cap | Static label "Understanding this goal", no indicator |
| 3 | Blueprint generated | Structure now exists | 420 chain, 60ms stagger | Requirement squares precipitate from the spine | All squares render at once, final state |
| 4 | Requirement appears | One more contract | 200 (micro) | Square scales 0.94→1 from its notch edge | Renders |
| 5 | Requirement approved | You committed to this | 240 | Notch closes; edge steps to full weight | Notch and weight render final |
| 6 | Tasks generated | The plan is executable work | 450 chain, 50ms stagger, dependency order | Branches draw out dashed | Branches render dashed, in final positions |
| 7 | Task becomes ready | This one can start now | 200 (micro) | Dash resolves to solid; tip cap appears | Style renders final |
| 8 | Task starts | Work left the spine | 280 | Capsule steps to full weight; transit begins | Capsule final; label → "Running"; transit suppressed |
| 9 | Route selected | A capability was matched, not a brand | 200 (micro) | Route glyph docks at the branch tip | Glyph renders |
| 10 | Attempt starts | Attempt N of this run | 160 (micro) | Tick marks onto the segment | Tick renders |
| 11 | Attempt fails | It did not reach the gate | 380 | Segment **retracts** to a visible gap; drops to 35% | Gap and 35% ghost render final; no retraction |
| 12 | Retry branches | TEMM is recovering, not failing | 400 | New segment offsets and begins transit; failed segment **stays visible** | Both segments render; label "Retrying — attempt N" |
| 13 | Effect detected | Something real changed on disk | 220 | Effect square materialises; single illumination pulse | Square renders |
| 14 | Gate evaluates | Measuring against your contract | 280 **per criterion**, sequential, chain-capped | Segments light one by one, illumination **across** the branch | Per-criterion pass/fail list renders at once, in order |
| 15 | Acceptance passes | Proven | 320 | Gate slot opens; branch completes through | Open gate and through-line render final |
| 16 | Acceptance fails | Measured, and refused | 320 | Failed segment struck; branch arrests flush at the gate | Struck segment, closed gate, flush arrest render final |
| 17 | Task completes | This work is now load-bearing | 400 | Branch merges into spine; spine steps up one weight; first green | Merge and weight step render final |
| 18 | Station collapses | This stage is settled | 280 | Station height collapses to a single line | Collapsed line renders |
| 19 | Project verifies | Completion is evidence-based | 420 | Spine settles to full weight, head to foot | Full weight renders |
| 20 | Deliverable assembles | The complexity has been resolved | 5-step chain, ≤1400ms | See §15 | Final composition renders: thick spine, seal, evidence stack, checksum |

`prefers-reduced-motion` and the existing `data-reduce-motion` preference are already wired
(`theme.css:109-110`) but currently zero **all** durations to `.001ms`, which is the blunt
version. The correct behaviour is the right-hand column above.

---

## 7. THE TEMM VERIFICATION SEAL

**Correction 4.** A signature verification geometry, derived from the spine and branch — not a
checkmark, not a shield, not a sparkle, not an AI star, not a badge, not a ribbon.

### 7.1 The idea

The seal is **the closed cell** — the shape that only exists because work left the spine and
came back.

Two branches depart the spine, travel, pass a gate, and converge. The region they enclose is the
seal. Its meaning is exact: *this area exists only because the work returned and was measured.*

**The single best property of this construction:** an unverified cell is **open**. The branches
depart, run parallel, and simply end — no convergence, no gate rule, no enclosed area.
Verification **closes the shape.** The seal is therefore not a symbol *of* verification; it is
verification, drawn. The same grammar as the lattice's "gap = failure", at brand scale.

### 7.2 Construction logic

On a **24-unit grid**, stroke weight 2 units, all angles 90° or 45°.

```
            │  y=0    spine enters (the goal)
            │
      ╱─────┴─────╲          y=4    departure, 45° chamfer
     │             │         y=10   parallel travel (the run)
     │             │
   ══╪═════════════╪══       y=15   THE GATE — the threshold, full cell width
     │             │
      ╲─────┬─────╱          y=21   convergence, 45° chamfer
            │
            │  y=24   spine exits (the deliverable)
```

**Three elements, no more:**

1. **The spine** — vertical stroke, `x=12`, from `y=0` to `y=24`, weight 2. It **overruns the
   cell at both ends**: the goal enters above, the deliverable leaves below. The overrun is not
   optional — it is what stops the mark reading as a static badge and keeps it reading as *a
   point on a continuous line*.
2. **The cell** — elongated hexagon. Vertices: `(12,4) (19,11) (19,15) (12,22) (5,15) (5,11)`.
   Two 45° chamfers top, two 45° chamfers bottom, two parallel vertical sides. Stroke weight 2,
   unfilled at rest.
3. **The gate** — single horizontal rule at `y=15`, `x=5` to `x=19`, weight 2. It sits exactly on
   the lower chamfer line, so the gate *is* the threshold the branches crossed to converge.

Nothing else. No inner mark, no glyph, no fill gradient, no aperture, no counter-form.

### 7.3 The state pair

| Form | Geometry | Meaning |
|---|---|---|
| **Open cell** | Chamfers at `y=4` present; verticals run to `y=15` and **end**. No lower chamfers. **No gate rule.** Spine continues through. | Work is out. Nothing is claimed. |
| **Closed cell (the Seal)** | Lower chamfers present, converging at `(12,22)`. Gate rule at `y=15`. | Measured, accepted, verified. |

The open form is the **completion motif** used throughout the product for in-progress work. The
closed form is the **Seal** and appears only on evidence-backed completion. They are the same
drawing at two moments, which means every in-progress surface in TEMM is already showing the seal
*unfinished* — and the user learns what completion looks like before they ever reach it.

### 7.4 The six reuses

| Use | Treatment |
|---|---|
| **Verified deliverable seal** | Closed cell at 96–160px, on the Deliverable station. Gate rule in verified green — the only saturated hue in the composition. Checksum set in mono directly beneath, optically aligned to the cell's width |
| **Completion motif** | Closed cell at 16–24px inline: beside a completed requirement, on a verified project row, on the export button. Green gate rule only; the cell stays ink |
| **Motion mark** | 5-step chain, ≤1400ms, exactly the §7.5 sequence. Loading identity and first-launch reveal |
| **App icon foundation** | Cell centred on a Graphite field; spine full-bleed vertically top to bottom edge (the overrun becomes literal bleed). Gate rule is the only accent. No rounded container styling of its own — the platform mask provides it |
| **Favicon** | 16px: spine + cell only. **Drop the gate rule below 20px** — it collapses into the chamfer at that size and muddies the silhouette. What survives is a hexagon pierced by a vertical bar, which is unmistakable and unlike any other product's favicon |
| **Package verification mark** | **Three cells stacked**, sharing one continuous spine — a chain of verified links. Used on exported artefacts, the ZIP, packaging documentation, and release surfaces. It says "a chain of evidence", which is literally what a TEMM deliverable is |

### 7.5 The motion mark — the 5-step chain

| Step | ms | Movement |
|---|---|---|
| 1 | 320 | Spine draws downward, `y=0 → y=24` |
| 2 | 360 | Upper chamfers open outward from `(12,4)`; verticals extend to `y=15` — **the open cell** |
| 3 | 280 | Gate rule draws outward from `x=12` to both edges at `y=15` |
| 4 | 360 | Lower chamfers converge to `(12,22)` — **the cell closes** |
| 5 | 200 | Spine steps to full weight; gate rule takes verified green |

Total ≈ 1400ms with 60ms overlaps. Within the chain law: 5 steps, none over 450ms.
**Reduced motion:** the closed seal renders in final state; no draw-on.

### 7.6 Why this is defensible

It is not a check, shield, star, sparkle, ribbon, badge, orb or hexagon-with-a-glyph-in-it. It is
derived entirely from the product's own load-bearing geometry, so it cannot be lifted from TEMM
without lifting the metaphor. It carries an honest state pair (open/closed) that most marks
cannot. It survives 16px. It composes into a chain. And it means something precise that the
product can actually prove.

---

## 8. TYPOGRAPHY LAW AND GUARDRAILS

**Correction 5.** The law is preserved; the scope of mono is narrowed hard.

> **Sans is human narrative. Mono is machine-measured fact.**

Applied consistently this becomes a reading instruction the user absorbs in minutes: mono means
*TEMM measured this*; sans means *a person wrote this*. It is progressive disclosure performed
typographically, and it is what lets receipts coexist with prose without dominating it.

### 8.1 Mono is permitted — and only here

1. **Measured values** — durations, byte sizes, token counts, exit codes, counts of changed files.
2. **Timestamps** — absolute times and ISO instants.
3. **Concise receipts** — a single line of measured outcome, e.g. `3 files · 1.2s · attempt 2`.
4. **Abbreviated hashes** — 7 characters, always, with the full value on copy.
5. **Technical evidence** — literal file paths, filenames, the exact literal token a criterion
   checks for, argv, environment key names.
6. **Expanded advanced details (L3)** — inside a disclosed technical receipt, mono may be the
   dominant face, because that region *is* machine output.

### 8.2 Mono is forbidden — explicitly

> **Mono may never be the dominant typography of a table, a navigation surface, a task, or a
> project narrative.**

| Forbidden | Correct treatment |
|---|---|
| **Tables** | Column *headers* and *labels* in sans. Numeric columns in **sans with tabular numerals**. Mono only in a dedicated hash/path column, and never more than one such column |
| **Navigation** | Always sans. No mono nav labels, no mono breadcrumbs, no mono tab labels |
| **Task titles and descriptions** | Always sans. A task is a human intention |
| **Project narrative** | Goal, understanding, requirement prose, state sentences, next actions, blocker explanations — always sans |
| **Acceptance criterion statements** | **Sans**, with only the literal checked token inline in mono. *Revised in this freeze:* "`src/index.css` must contain `@import "tailwindcss"`" is a sentence a person reads, not a machine dump. Revision 1 made the whole statement mono, which would have made the entire Requirements Approval screen dominantly monospace. That is withdrawn |
| **Empty states, errors, confirmations** | Always sans |
| **Headings at any level** | Always sans |
| **Buttons and controls** | Always sans |

### 8.3 The inline rule

> **Mono appears inline, not structurally.** A mono run is a *chip or a fragment inside a sans
> sentence*, not a block that sets the page's texture. The one exception is L3, where machine
> output legitimately owns the region.

Practical test: **squint at any L1 or L2 screen. If the page reads as monospace, the rule is
broken.** A screen should read as well-set prose with precise measured fragments embedded in it.

### 8.4 Families

- **Sans** — a grotesque with **true tabular numerals** and low stroke contrast. Manrope (already
  installed) is acceptable and can carry V1–V3; it is slightly soft for the instrument reference
  class, so a candidate swap is worth evaluating before V8. **Tabular numerals are
  non-negotiable** — every count, duration and metric must align in a column.
- **Mono** — a technical mono with unmistakable `0/O`, `1/l/I` and a narrow advance so 64-char
  hashes are tractable at L3. Currently `'Cascadia Code', 'SFMono-Regular', Consolas` with **no
  bundled fallback**, so the single most precision-critical text class in the product renders
  machine-dependently. This must be fixed in V1.
- **Arabic** — Alexandria (already installed) stays. Every type token must be validated at Arabic
  optical sizes; Arabic wants more line-height and generally reads one step larger. **The 12px
  floor may need to be 13px for Arabic** — resolve empirically in V1.
- **Arabic and mono** — Arabic never sets in mono. A measured value inside Arabic prose stays
  `dir=ltr` in the mono family, which `theme.css:108` already enforces correctly.

### 8.5 The scale — 8 steps, one ratio

Base **15px**, ratio **1.2**. Replaces 28 arbitrary sizes.

| Token | Size | Use |
|---|---|---|
| `--type-900` | 43px | Goal. First-launch question. One per screen, often zero |
| `--type-800` | 36px | Deliverable name. Signature moments |
| `--type-700` | 26px | Station heading |
| `--type-600` | 22px | Object title — task, requirement |
| `--type-500` | 18px | Sub-heading, emphasised value |
| `--type-400` | **15px** | **Body. The default. The most-used size in the product** |
| `--type-300` | 13px | Secondary, supporting |
| `--type-200` | 12px | **Floor.** Labels, mono chips |

**12px is the floor.** All 207 declarations currently below 10px are defects. The eyebrow/kicker
pattern currently at 8–8.5px becomes 12px, with letter-spacing and weight doing the work that
small size was wrongly asked to do.

---

## 9. DESIGN TOKENS

### 9.1 Spacing — 4px base, 8 steps

`4 · 8 · 12 · 16 · 24 · 32 · 48 · 64`. All 484 hardcoded values map onto these. Station rhythm is
`32` internal, `48` between. No value outside the scale is permitted.

### 9.2 Radii — 4 values, down from 17

| Token | Value | Use |
|---|---|---|
| `--radius-chip` | 4px | Mono chips, ticks, effect squares |
| `--radius-object` | 8px | L2 objects, inputs, buttons |
| `--radius-overlay` | 14px | L3 overlays and sheets |
| `--radius-capsule` | 999px | **Task capsules only** — the capsule is a semantic shape, not decoration |

Goal cap, requirement square and seal use **chamfers, not radii** — a 6px 45° corner cut. That
one geometric decision carries most of the instrument character, and it is nearly free.

### 9.3 Line weights — semantic, not stylistic

`1 · 1.5 · 2 · 3px`. This is the spine's evidence-accumulation scale. Weight is **information**
and may not be used decoratively.

### 9.4 Surfaces and elevation

Four depth levels. Depth, not colour.

- **L0 Canvas** — the field. Holds the spine. Never holds text directly.
- **L1 Station** — a section of the project story. Hairline top rule, **no border box, no
  shadow**. Stations separate by space and rule. This alone removes most of the card-grid look.
- **L2 Object** — a task, gate, evidence chip. Has a border. Interactive.
- **L3 Overlay** — modal or sheet. **The only level with a shadow.**

Elevation is used exactly once. The current three-tier shadow system goes away.

### 9.5 Canvas

**Dark-first.** Luminance is TEMM's primary signal carrier and luminance needs darkness to read
as *illumination* rather than *tint*.

- **Graphite** — dark, primary. Warm-neutral, **not blue-black**; blue-black is the AI-product
  tell.
- **Chalk** — light, fully supported, understood as secondary. On Chalk, "illuminated" inverts to
  "most-inked": the live line becomes the *darkest* line, not the brightest. The grammar
  survives; the mechanism flips. Both modes must pass §5.3.

### 9.6 Empty, loading, focus, hover, press

- **Empty states** — one sentence, one action. Not illustrations, not cards. The 8 `TruthState`
  variants in `StateNotice.tsx` currently render as one shape differing only by icon, so
  `unknown` and `error` are near-identical. Collapse to **four**: empty / waiting / attention /
  error, each with distinct geometry.
- **Loading** — skeletons **never shimmer**. A loading station draws its hairline rule and its
  heading and leaves the content region empty. Shimmer is decorative motion and violates §6.
- **Focus** — 2px offset ring in ink, ≥3:1 against both component and surface. Never removed,
  never hue-only.
- **Hover** — a weight or luminance change. **Never a transform.** The current `translateY(-1px)`
  button lift is SaaS vocabulary and goes.
- **Press** — a luminance drop, 120ms.

---

## 10. WORK GRAPH — PROGRESSIVE DISCLOSURE

Three levels. **Level 1 must be complete on its own:** a user who never opens Level 2 must still
be able to run a project to a verified deliverable.

**LEVEL 1 — project state in human language. Default. Always sufficient.**
Permitted: the goal, what TEMM understood, what will be built, what is happening now, what needs
a decision, what finished, what you get. Task titles. Capability names. Counts. Human durations.
**Forbidden:** run, attempt, route, executor, provider, model, adapter, revision, workspace ID,
checkpoint, orchestration, dispatch, evaluator type, provenance, `lifecycle_status`, and every
other schema term — plus any ID, hash, absolute path, or JSON.

**LEVEL 2 — tasks, dependencies, progress. One interaction away. Where the meso spine lives.**
Adds: the lattice, dependency order, what blocks what, which task is executing, per-task
acceptance criteria as **statements** (sans, per §8.2), attempt count as a plain number, elapsed
time. Still forbidden: raw IDs, hashes, JSON, provider/model names.

**LEVEL 3 — technical receipt. Two interactions away. Complete and uncompromised.**
Everything: run ID, attempt ID, executor type, agent ID, model route with provenance, argv, cwd,
permission profile, derived write scope, prompt fingerprint, pre/post workspace hashes, scoped
diff, per-criterion evaluator output, stdout/stderr, completion reason, full SHA-256.

L3 must be **excellent, not hidden.** TEMM's receipts are a genuine competitive asset. The rule
is not "hide the truth" — it is **"never make a normal user step over it."**

### Concrete corrections this forces

- `RunDetails.tsx` renders five schema-named cards **unconditionally under every success**
  (`RunWorkspace.tsx:489`). That entire component is L3 and must not appear by default.
- Both full 64-char SHA-256s in default views (`FleetManager.tsx:275`, `Projects.tsx:260`) become
  7-character mono chips that copy the full value; the full string lives at L3.
- All 6 un-collapsed `<pre>` blocks move to L3.
- The ~18 raw enums get human labels at L1/L2 and keep their raw value at L3 only.
- `Projects.tsx:255`'s JSON dump of `required_capabilities / capability_basis / blockers /
  execution_method / selected_route` becomes, at L1, one sentence and one button: *"Coding
  capability required"* → *"Sign in to your coding tool."* The JSON stays, at L3.

---

## 11. RESPONSIVE AND DENSITY BEHAVIOUR

**Correction 6.** A desktop lattice must never simply shrink onto mobile. Two independent
variables interact — **viewport width** and **task count** — so the behaviour is a matrix, not a
list of breakpoints.

### 11.1 Viewport tiers

| Tier | Width | Spine treatment | Lattice treatment |
|---|---|---|---|
| **Wide desktop** | ≥1600px | Macro spine as a fixed leading rail, always visible. Content column capped at 72ch — **the extra width becomes lattice breathing room, never longer text lines** | Full lattice with lateral branch travel and a persistent task detail **side sheet** open alongside |
| **Normal desktop** | 1200–1599px | Macro spine as leading rail, always visible | Full lattice, lateral branches. Task detail is an **overlay sheet** |
| **Tablet** | 760–1199px | Macro spine **collapses to a 6-dot progress rail** pinned in the sticky header. It stops being a full-height rail | Lattice becomes **vertical-dominant**: branches shorten, dependency depth carries the reading, parallelism shown by horizontal offset only. Attempts fold to a count |
| **Mobile** | <760px | **No lattice.** Macro spine becomes a 6-dot rail in the header | The meso spine is replaced by the **Task Ledger** — see 11.3 |

### 11.2 Task-count tiers — preserved from revision 1

| Tasks | Representation |
|---|---|
| **1–24** | **Full lattice.** Every task a capsule, every gate segmented, up to 3 attempt segments visible |
| **25–80** | **Grouped lattice.** The *requirement* becomes the branch; its tasks become that branch's weight plus a count. Expanding one requirement expands its sub-lattice inline; **siblings collapse**. Attempts collapse to a count badge |
| **>80** | **The Ledger.** A typographically-driven list ordered by dependency depth, with the micro spine as a 24px inline column. The lattice demotes to a **minimap**, not the primary readout |

**Attempt folding is global:** never more than **3 visible attempt segments**; beyond that,
`+N earlier attempts`, expandable. Six parallel offset segments is unreadable, and the design
says so rather than discovering it in implementation.

### 11.3 The Task Ledger — the mobile and >80 representation

Not a shrunken lattice. A different, first-class representation of the same truth.

- One row per task, ordered by dependency depth. Depth shown by a **leading indent rail**, not by
  drawn edges.
- Each row: state geometry chip (§5) · task title (sans, `--type-400`) · one measured line (mono,
  `--type-200`) · disclosure chevron.
- The **micro spine** (§3.3) renders inline at 24px in a fixed leading column, and it is the only
  spine geometry present. It shows: effect present, gate segment count, gate open/closed/struck.
- Blockers **hoist to the top of the ledger**, above all other rows, regardless of dependency
  order. Attention outranks sequence.
- Grouping on mobile is **by requirement**, always, at every task count — because a mobile user is
  answering "is my project moving?", not tracing a graph.

### 11.4 What is removed as the viewport narrows

Progressive removal, in this order. Each item is removed **before** any type size is reduced —
**type never shrinks below the 12px floor at any viewport.**

1. Route glyphs and capability labels on branches → move into the task row's disclosure.
2. Gate segment labels → segment count only; labels on disclosure.
3. Lateral branch travel → vertical stacking.
4. Attempt segments → attempt count.
5. Evidence chips inline → an "evidence" disclosure per task.
6. **All L3 affordances** → on mobile, the technical receipt is reachable but is a full-screen
   route, never an inline expansion.
7. The dependency hover-raise interaction → replaced by 11.5.

### 11.5 Touch interaction

- **Minimum target 44×44px.** Lattice nodes at desktop are smaller than this, which is the honest
  reason the lattice is not the mobile representation.
- **No hover state may carry unique information.** The desktop dependency hover-raise must have a
  tap equivalent: **tap a task → its dependencies and dependents raise to full ink and the rest
  drop to 25%, and it stays latched until tapped again or dismissed.** Latched, not transient,
  because touch has no hover.
- **No drag, no pinch-zoom, no pan** on the lattice. If a representation needs panning to be
  read, the wrong representation was chosen for that viewport — that is what 11.1 exists to
  prevent.
- Sheets present as **bottom sheets** on mobile and tablet, **side sheets** on desktop.
- Swipe is never the only path to an action.

### 11.6 The composite matrix

| | ≤24 tasks | 25–80 | >80 |
|---|---|---|---|
| **Wide desktop** | Full lattice + persistent side sheet | Grouped lattice + side sheet | Ledger + lattice minimap |
| **Normal desktop** | Full lattice | Grouped lattice | Ledger + lattice minimap |
| **Tablet** | Vertical lattice, attempts folded | Grouped vertical lattice | Ledger |
| **Mobile** | Ledger, grouped by requirement | Ledger, grouped by requirement | Ledger, grouped by requirement, collapsed by default |

**Verification gate for §11:** the work graph is correct and readable at 1, 6, 24, 40 and 120
tasks, at 1600 / 1440 / 768 / 375, in EN and AR, with no horizontal overflow and no type below
12px.

---

## 12. RTL DIRECTION LAW

**Correction 7.** The revision-1 claim "vertical is inherently RTL-safe" was too glib and is
formalised here. The spine is direction-neutral; **the branches are not.**

> **THE DIRECTION LAW.**
> **1.** The spine is direction-neutral. It runs top to bottom in every locale.
> **2.** Branches obey **semantic travel direction: toward the verification gate.** Never
> "rightward", never "leftward".
> **3.** Attempts and sequence order by **travel/progression semantics** — along the branch's own
> direction of travel — never by a hardcoded left-to-right axis.
> **4.** **Arabic must never reverse temporal or causal meaning.**

### 12.1 Mirrored — must flip under `dir=rtl`

| Element | Behaviour |
|---|---|
| Spine rail **position** | Leading edge (`inset-inline-start`). Left in LTR, right in RTL |
| Branch **departure direction** | Toward `inline-end`. Rightward in LTR, leftward in RTL |
| Gate slot and its criterion segments | Mirror with the branch; segment **order follows travel**, so criterion 1 is always the first one the branch meets |
| Route glyph docking side | Branch tip, which mirrors |
| Evidence chip docking side | Mirrors |
| Ledger indent rail | Leading edge |
| Disclosure chevrons | Point toward `inline-end` when collapsed |
| Station heading and text alignment | `text-align: start` |
| Side sheets | Enter from `inline-end` |
| Macro spine 6-dot rail (tablet/mobile) | Progresses toward `inline-end` |
| Nav, sidebar, layout | Logical properties only |

### 12.2 Non-mirrored — must NOT flip

| Element | Why |
|---|---|
| **Spine axis** | Vertical in every locale. Progress is downward everywhere |
| **Macro station order** | Goal → Blueprint → Requirements → Execution → Evidence → Deliverable, top to bottom, always. **This is causal order and must never reverse** |
| **Dependency depth axis** | Downward. Deeper dependency = further down, in every locale |
| **Attempt order** | Along travel direction. Attempt 1 is always the one nearest the task; attempt N always nearest the gate |
| **Transit direction** | Toward the gate — defined semantically, so it mirrors *automatically* and cannot be wrong |
| **Timeline / chronology in receipts** | Earliest at top, latest at bottom. **Never horizontal**, precisely so it cannot reverse |
| **Numerals in measured values** | Western digits, `dir=ltr`, mono |
| **Hashes, paths, argv, code, terminal output** | `dir=ltr`, mono. `theme.css:108` already enforces this correctly |
| **The Verification Seal** | Vertically symmetric about its own spine; identical in both locales. No mirrored variant exists |
| **Progress weight steps** | Thin → thick, bottom-anchored, direction-independent |

### 12.3 The hazard this closes

The genuine RTL trap is **an attempt sequence laid out left-to-right.** Under `dir=rtl` an
attempt strip ordered "later = further right" silently reverses: an Arabic reader scanning
right-to-left reads attempt 3 first and infers that the *newest* attempt came *first*. That is a
reversal of causality, which is far worse than a layout bug — it makes the interface lie about
what TEMM did.

**The fix is definitional, not conditional:** attempts are ordered *along the branch's direction
of travel toward the gate*. Because travel direction mirrors with the branch, the ordering
mirrors with it, and no locale-specific branch is needed anywhere in the design.

**Verification gate for §12:** every lattice state screenshotted side-by-side EN/AR; a native
Arabic reader confirms that in no state does the interface imply a different order of events than
the English rendering.

---

## 13. FLAGSHIP PROJECT WORKSPACE

**Correction 8.** One canonical composition, specified before any token work. This is the
signature TEMM screen. It is **not** a grid of SaaS cards, and no part of it is a card.

Specified at **Normal desktop, 1440×900, ≤24 tasks, mid-execution** — the state in which the
screen must be most impressive and most useful. Other viewports derive per §11.

### 13.1 The frame

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  TEMM     Projects   Tools   Settings                          ⌕   ☾   ع    │  56px chrome
├───┬──────────────────────────────────────────────────────────────────────────┤
│   │  Build a booking site for the clinic                        ⬡ Running    │  STICKY
│ ▪ │  Task 3 of 7 · verifying acceptance · 2m 14s                             │  OUTCOME
│ │ │                                            ┌──────────────────────────┐  │  132px
│ ◫ │                                            │  Continue execution   ▸  │  │
│ │ │                                            └──────────────────────────┘  │
├ │ ┼──────────────────────────────────────────────────────────────────────────┤
│ ◨ │                                                                          │
│ │ │  UNDERSTOOD ─────────────────────────────── 6 requirements approved   ▸  │  collapsed
│ │ │                                                                          │  40px
│ ═ ├──────────────────────────────────────────────────────────────────────────┤
│ │ │                                                                          │
│ │ │  WORK                                                       3 of 7 done  │  MESO SPINE
│ │ │                                                                          │  the lattice
│ │ │      │                                                                   │  fluid height
│ │ │      ├──────────────═══════════▶  Set up the project        ✓ accepted   │
│ │ │     ═╡                                                                   │
│ │ │      ├──────────────═══════════▶  Build the booking form    ✓ accepted   │
│ │ │     ═╡                                                                   │
│ │ │      ├───────▶─────┬─┬─┐                                                 │
│ │ │      │       ▪   ══╡ │ │╞══      Connect the calendar      ◈ verifying  │
│ │ │      │             └─┴─┴─┘                                              │
│ │ │      ├──────────╴╴╴╴  ✕          Send confirmations        ⊘ not accepted│
│ │ │      ├──────────▶───────────      (retry, attempt 2)                     │
│ │ │      │                                                                   │
│ │ │      ├╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴            Style the pages           ○ planned    │
│ │ │      ├╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴            Add the contact page      ○ planned    │
│ │ │      ├╴╴╴╴╴╴╴  ╎                 Publish                   ⌀ blocked    │
│ │ │      │                                                                   │
│ ▤ ├──────────────────────────────────────────────────────────────────────────┤
│ │ │  EVIDENCE ──────────────── 2 accepted · 3 files measured             ▸   │  collapsed
│ │ ├──────────────────────────────────────────────────────────────────────────┤
│ ⬡ │  DELIVERABLE ─────────────────── available when all work is verified     │  dormant
└───┴──────────────────────────────────────────────────────────────────────────┘
   ▲
   macro spine, fixed leading rail, full height
```

### 13.2 Vertical hierarchy, top to bottom

**Chrome — 56px.** Four nav items only: Projects · Tools · Settings, plus the product mark.
Search, theme, language. **No project data lives in the chrome.** The chrome is furniture.

**1. OUTCOME — sticky, 132px, never collapses.** The single most important region in the product.
Three lines and one button:
- **The goal**, `--type-700` sans, the owner's words verbatim, up to two lines then a disclosure.
  It is the largest text on the screen and it never leaves the viewport.
- **The state sentence**, `--type-400` sans: *"Task 3 of 7 · verifying acceptance · 2m 14s."* A
  sentence, never a badge alone. Measured values within it are mono, inline.
- **The state mark** — the §5 geometry for the project's current state, trailing edge, 24px.
- **One primary action.** Exactly one, ever. Its label is the next real action:
  *Understand this goal · Approve blueprint · Approve requirements · Start execution · Continue
  execution · Resolve blocker · Download deliverable.* This is the promotion of the existing
  `spine-next-action` pattern (`Projects.tsx:254`) to permanent residence.

**2. UNDERSTOOD — collapses to 40px on approval.** Expanded: the blueprint and the requirement
squares. Collapsed: one line, `UNDERSTOOD ─── 6 requirements approved ▸`. Clarification questions
appear **inline on the requirement they belong to**, never as a separate form section.

**3. WORK — the meso spine. Fluid height. The visual centre of gravity.** The lattice. Never
collapses while the project is incomplete. This is the only station that grows.

**4. EVIDENCE — collapsed by default, always.** One line: `EVIDENCE ─── 2 accepted · 3 files
measured ▸`. Expands to the evidence stack: one micro spine (§3.3) per accepted task, each with
its measured effect and its gate result. Full receipts are one further disclosure (L3).

**5. DELIVERABLE — dormant until earned.** Present but inert, showing only *"available when all
work is verified."* **No green, no seal, no download affordance, no progress bar toward it.** Its
dormancy is honest and it is the visual promise the whole screen is working toward.

**6. ATTENTION — not in the sequence. It preempts it.** See 13.5.

### 13.3 Centre to periphery

- **Centre** — the lattice. Highest ink, highest information density, the only motion.
- **Near periphery** — the sticky Outcome above, the collapsed Evidence and Deliverable below.
  Present, legible, low ink.
- **Far periphery** — the macro spine rail (leading edge) and the chrome (top). Structural
  orientation only, lowest ink, never competing.
- **The rail is the anchor.** The macro spine runs the full viewport height at the leading edge,
  and the currently-active station's node on it is the only one at full weight. A user glancing at
  the rail alone knows which of the six lifecycle stages they are in.

### 13.4 The nine mechanics, precisely located

| Mechanic | Location and behaviour |
|---|---|
| **Where the spine begins** | Macro: the Goal cap at the top of the leading rail, `y=0` of the viewport, drawn from the goal text at project creation. Meso: the vertical stroke at the leading edge **of the WORK station only**, beginning at the station's top rule |
| **Where branches form** | On the meso spine, at a vertical position set by **dependency depth**. Depth 0 tasks branch nearest the top. Branches depart toward `inline-end` (§12) |
| **Where tasks execute** | Along the branch, between departure and gate. The capsule sits at the branch's mid-length; transit runs capsule → gate |
| **How attempts appear** | Parallel offset segments on the same branch, offset perpendicular by one line-weight step. Attempt 1 nearest the task, attempt N nearest the gate — ordered by travel, per §12. Max 3 visible, then `+N earlier attempts` |
| **Where acceptance gates live** | At the branch's terminus, immediately before the merge point. One slot per task, segmented one per typed criterion. **The gate is drawn only once criteria have been measured** (§3.3) — never speculatively |
| **How evidence returns** | An effect square materialises on the branch at the point of measurement. When the gate opens, the branch **completes through it into the spine** and the spine steps up one weight. The evidence chip then **docks into the collapsed Evidence station**, which increments its count. Evidence physically travels from the branch to the station |
| **Where blockers appear** | Twice, deliberately. **(a)** In place on the lattice, as the §5 Blocked geometry — a gap before the gate, so the user can see *which* work is stopped and what it was waiting on. **(b)** Hoisted into the **Attention station**, which preempts the whole composition (13.5). The lattice keeps context; the Attention station forces the decision |
| **Where the Deliverable forms** | At the foot of the macro spine rail, in the Deliverable station. It forms only via the §15 convergence chain, and only when completion is evidence-based |
| **Where technical truth lives** | Behind exactly one control per object, labelled *Technical receipt*. Never in the default composition. Never a `<pre>` on the primary surface |

### 13.5 The Attention rule

> **When a decision is required, the Attention station takes the position immediately below the
> Outcome header, and every station except Outcome desaturates to ~20% ink.**

This is the correction to current behaviour, where a blocker is one of eight equally-weighted
`surface-card`s and `readiness-blockers` has no CSS rule at all. **A blocker is not a card. It is
a stop.** One blocker, one sentence, one action, nothing competing.

- The sentence is capability-led and actionable — the existing copy at `Projects.tsx:175-195` is
  already correct ("Connect project folder", "Sign in to your coding tool", "Coding capability
  required") and only needs presentation.
- **No motion.** A stop does not animate. That absence is itself information: the product's pulse
  stopped.
- The lattice remains visible at 20% behind it, so the user sees *what* is stopped without losing
  the decision.
- Multiple blockers: the **first actionable one** is presented; the rest are a count.

### 13.6 What must NOT be visible in the flagship composition

Runs. Attempts as records. Routes. Executors. Models. Providers. Adapters. Workspace IDs.
Checkpoint state. Orchestration state. Dispatch mechanics. Evaluator type names. Revisions.
Hashes beyond a 7-char chip. JSON. Absolute paths. `capability_basis`. "Technical readiness
details". Tabs. Any `surface-card` border around a station. Any shadow outside L3. Any green that
was not earned.

---

## 14. FIRST LIVE EXECUTION MOMENT

**Correction 9.** The exact sequence when the user presses **Start execution**. Every step is
bound to a real system state transition. **No step may run on a timer, an estimate, or an
optimistic assumption.**

> **THE NO-FAKE-PROGRESS LAW.** Every frame of this sequence is driven by an observed state
> change. There is no interpolation between states, no predicted progress, no percentage that was
> not measured, and no step that plays before the system fact it depicts exists. If TEMM does not
> yet know, the interface shows the last true state and says what it is waiting for.

### 14.1 The sequence

| # | Trigger — real system fact | Visual | ms |
|---|---|---|---|
| 0 | Press registered | Button press, micro | 140 |
| 1 | Plan compiled / existing checkpoint resumed | **The approved blueprint settles**: the UNDERSTOOD station collapses to its single line; the macro spine's weight steps from Requirements to Execution | 320 |
| 2 | Readiness resolved `ready=true` | Capability confirmation appears in the state sentence: *"Coding capability ready."* Route glyph docks at the first branch tip. **If readiness resolves false, the chain aborts here** and the Attention station preempts — no branch is drawn, because no work started | 200 |
| 3 | Task moves `planned → ready` | **The ready task illuminates**: its branch's dash resolves to solid; the capsule gains its tip cap and steps to full weight. **Only tasks the dispatcher actually made ready illuminate** — a dependency-blocked sibling stays dashed | 280 |
| 4 | Run created | **The branch enters transit**: sustained illumination begins, capsule → gate. The one continuously moving element on screen | begins, 1200ms cycle |
| 5 | Attempt created, `attempt_number` known | **The attempt segment begins**: a tick marks onto the segment. On attempt ≥2 a parallel offset segment forms and the prior one drops to 35% | 160 |
| 6 | Executor bound — `executor_type`, capability | **Execution route becomes visible**: the route glyph resolves from generic to its capability label. **Capability, never brand** — `Coding capability`, never a model ID | 200 |
| 7 | Filesystem effect measured, scoped diff non-empty | **Evidence arrives**: an effect square materialises on the branch at the measurement point, with one illumination pulse. **A zero-diff run draws no square** — and therefore the branch is visibly unable to reach the gate, which is exactly TEMM's `no_effect` truth | 220 |
| 8 | Acceptance evaluation begins | **The gate draws** — now, and not before, because only now are there measured criteria to segment it by (§3.3) | 280 |
| 9 | Each criterion resolves | **The gate evaluates**: one segment lights per criterion, sequentially, illumination travelling *across* the branch. Passed segments hold; a failed segment is **struck with a diagonal** | 280 per criterion, chain-capped ≤1400ms |
| 10a | All criteria pass → task `completed` | **Accepted evidence rejoins the spine**: the gate slot opens, the branch completes through at full weight, the spine steps up one weight, the evidence chip docks into the Evidence station, and **verified green appears** — for the first time in the session | 320 + 400 |
| 10b | Any criterion fails → task `blocked` | **The branch arrests flush against the closed gate.** The failed segment stays struck. Clay. The state sentence names the failed criterion. Transit stops instantly | 320 |
| 11 | Dispatcher reports nothing further moved | Transit ceases. The Outcome header updates to the true count. The primary action becomes **Continue execution** if work remains, or the §15 chain fires if completion is evidence-based | 200 |

Chain discipline: steps 1–3 are one chain (≤1400ms). Steps 4–11 are **not a chain** — they are
individual structural events fired by real transitions, arriving whenever the system actually
transitions, which may be seconds or minutes apart. **The interface waits. It does not fill the
gap with animation.**

### 14.2 What the sequence teaches

By step 10 the user has seen, without reading documentation: the plan settling, readiness being
checked before anything ran, only genuinely-ready work starting, a capability rather than a brand
being chosen, a real attempt beginning, a real file changing, a gate being built from *their*
criteria, those criteria measured one by one, and — only then — green.

If the first task instead fails, the user learns something more valuable in the same window:
**TEMM arrests at the gate, names the criterion, keeps the failed attempt visible, and re-routes.**
The failure path is not a degraded version of this experience. It is the more persuasive one.

### 14.3 Waiting states

While a step's system fact has not yet arrived, the interface shows the **last true state** plus a
sentence naming what it is waiting for: *"Waiting for the executor to report changes."* Permitted
motion during a wait: the sustained transit only, and only if a run is genuinely active. **No
spinner. No skeleton. No progress bar.** A progress bar that cannot be measured is a lie, and this
product's entire thesis is the refusal to make unmeasured claims.

---

## 15. DELIVERABLE CONVERGENCE

**Correction 10.** The one signature moment. It must be earned, brief, and honest. No confetti,
no fireworks, no sound, no full-screen takeover.

### 15.1 What must be communicated

> *"The complexity has been resolved — and verified."*

The mechanism is **reduction**. The screen the user is left with contains **fewer marks** than the
screen they were watching a moment earlier. The emptiness is the reward.

### 15.2 The chain — 5 structural steps, ≤1400ms, once per project

| Step | ms | Movement | Communicates |
|---|---|---|---|
| **1. Stillness** | 0 → 180 | **All motion stops.** Every transit ceases. Every branch settles. Nothing moves. | The product has been moving for minutes and suddenly is not. **Stillness is the signal.** |
| **2. Gates resolve** | 180 → 480 | Every remaining gate slot opens, in dependency order, 40ms apart, head to foot | Every contract has been measured |
| **3. Evidence converges** | 480 → 840 | Evidence chips **detach from their branches and travel down the spine**, converging into a single stack at the foot | Distributed proof becomes **one** proof |
| **4. Branches retire** | 840 → 1160 | Accepted branches fade to hairline ghosts. The lattice thins. **The screen gets emptier** | Complexity resolved — the many become the one |
| **5. Seal closes** | 1160 → 1400 | The §7 open cell at the foot of the spine **closes**: gate rule draws, lower chamfers converge, the gate rule takes verified green | Verified |

Total ≈1400ms across 5 steps, none exceeding 320ms. Within the chain law. **Fires once per
project, ever** — never on re-render, re-mount, or navigation return.

### 15.3 The resting composition

```
        ▪   Build a booking site for the clinic
        │
        │        ← one spine, full weight
        │
    ╱───┴───╲
   │         │
 ══╪═════════╪══      ← the Seal, closed, gate rule in verified green
   │         │
    ╲───┬───╱
        │
        ▤   clinic-booking · 0.1.0
            a1b3f9c · 412 KB · 7 tasks verified
            ┌──────────────────┐
            │  Download     ▾  │
            └──────────────────┘
            What was verified  ▸
```

- **Hierarchy** — the Seal is the largest object. Then the deliverable name (`--type-800`, sans).
  Then the receipt line (mono, `--type-200`). Then the download action. Then one disclosure.
- **Verification seal behaviour** — the closed cell at 96–160px. Its gate rule is the only
  saturated hue in the composition. It draws **only** when `completion.ready` is true from
  evidence. **There is no provisional, optimistic, or early seal.**
- **Package/artifact reveal** — the artefact is *named*, not illustrated. No box icon, no
  document illustration, no folder graphic. Name, version, size, task count. The **package
  verification mark** (§7.4, three stacked cells) marks the exported artefact itself and any
  packaging documentation.
- **Checksum placement** — the 7-character abbreviated hash sits in the receipt line, mono,
  directly beneath the deliverable name, **optically aligned to the seal's width**. It is
  positioned as a *signature under a mark*, because that is what it is. Click copies the full
  64-character value. The full string appears only at L3.
- **Evidence placement** — `What was verified ▸` expands the full chain: every requirement, every
  task, every gate result, every measured effect, each as a micro spine (§3.3). This is the
  product's proof of work and it is one click away, not hidden and not forced.

### 15.4 Honesty constraints

- The chain fires **only** when completion is evidence-based. Nothing about it is decorative.
- **If any requirement is uncredited, there is no convergence at all** — the Attention station
  preempts instead. A partial project must never receive a partial celebration.
- If the deliverable cannot be packaged (no acceptance-measured artefact path — a real limitation
  recorded in the handoff), the seal still closes on the *verified work*, and the packaging
  limitation is stated plainly as a separate sentence. **Verification and packaging are different
  claims and must not be conflated.**
- **Reduced motion** — the resting composition renders in final state. Step 1's stillness is
  preserved automatically, because reduced-motion users had no motion to stop.

---

## 16. EXECUTION AND RECOVERY VISUALIZATION

The user must see execution happening and — critically — **recovery** happening, because recovery
is what TEMM is genuinely good at and it is currently invisible.

### 16.1 The travel

```
        │  spine — verified progress, weight = accumulated evidence
        │
        ├──────────────────────╴╴╴╴╴   PLANNED     dashed hairline
        │
        ├──────────────────────────    READY       solid hairline, tip capped
        │                        ◇     route glyph docks (capability)
        │
        ├───────▶───────────────────    RUNNING    illumination travels toward gate
        │           ▪                   effect measured
        │        ┌─┬─┬─┐
        │      ══╡ │ │ ╞══              GATE       one segment per typed criterion
        │        └─┴─┴─┘
        │
        ├───────────────────═════▶      ACCEPTED   branch completes through the open gate
       ═╡                               spine steps up one weight
        ║
```

### 16.2 Failure is a branch, never a red card

```
        │
        ├───────────────╴╴  ✕          attempt 1 — retracted, gap before the gate,
        │                              35% ghost. HISTORY IS PRESERVED
        ├─────────▶──────────          attempt 2 — offset segment, live transit
        │       ◇                      different capability route
        │        ▪
        │      ══╡ │ │ ╞══
        │
```

Three properties that matter:

1. **The failed attempt does not disappear.** The user sees that TEMM tried, did not reach the
   gate, and tried again differently. That is trust, and it is the visual form of the engineering
   fact that TEMM retains failed evidence rather than resetting it.
2. **The gap is the failure indicator, not colour.** Clay tints the retracted segment, but the
   information is carried by *not reaching*.
3. **Successful evidence converges back.** When attempt 2 produces an effect and the gate opens,
   the branch completes into the spine and the failed segment fades to a hairline ghost. The record
   remains; the weight does not. **Only proven work becomes load-bearing.**

### 16.3 Three failure modes, three geometries

| Mode | Geometry | System fact |
|---|---|---|
| **Blocked** | Gap **before** the gate, no transit, no gate drawn | Never dispatched, or dependency/readiness unmet |
| **No effect** | Branch in transit completed, but **no effect square**, so it cannot reach the gate | Exit 0 with an empty scoped diff — TEMM's `no_effect` |
| **Rejected** | Branch **flush against a closed gate**, failed segment struck | `acceptance_unsatisfied` — measured and refused |

These three are the honest heart of the product and they have never been drawn. Making them
visually distinct is the single highest-value thing the lattice does.

### 16.4 The Now line

One line, always, in the Outcome header: *"Task 3 of 7 · Running · Coding capability · 2m 14s ·
attempt 2."* Measured fragments in mono, prose in sans (§8.3).

The existing `LiveTerminal` (xterm, already wired, already handles reconnect and cancellation)
belongs here as an L3 disclosure: **Show executor output.** Raw PTY is genuine evidence and must
be one click away — but it is not the default face of execution. Note that its footer currently
prints `WebSocket open` and `Interactive · PTY` (`LiveTerminal.tsx:125,129`) — transport
vocabulary in product chrome, which is L3 language.

---

## 17. KEY SCREEN ART DIRECTION

Twelve screens. Each: hierarchy, major object, interaction, motion, and what must **not** be
visible by default.

**1. First launch.** One question, one field, nothing else. Graphite. The §7.5 motion mark draws
first, teaching the metaphor before any UI exists. Major object: **"What do you want finished?"**
at `--type-900`. *Not visible:* sidebar, nav, settings, providers, models, tools, scan, the current
6-step wizard, the current setup guide, **and any green pixel.**
The current onboarding leads `01 DISCOVER → 02 CONNECT → 03 WORKSPACE → 04 DEFAULTS`, which is
infrastructure-first and contradicts the handoff's own principle that the experience must begin
from a goal. All four are resolvable later, at the moment execution needs them — which the
readiness gate already does properly.

**2. Goal / project creation.** The typed words settle into the goal cap and stay, verbatim. The
name is *derived* and offered as editable secondary, not demanded — the current form blocks on
both `name` and `purpose` (`Projects.tsx:94`), which asks for a slug before an outcome.
*Not visible:* project type, slug, owner, template, blueprint source.

**3. Project Workspace.** §13, in full. The signature screen.

**4. Blueprint review.** "Here is what I understood" → the understanding → approve or correct.
Major object: the field of requirement squares precipitating from the spine — the first time the
user sees *structure* emerge from *prose*, which is COMPLEXITY → COORDINATION made literal.
Clarification questions inline on their own requirement. *Not visible:* blueprint ID, revision,
template ID, `proposal_id`, evaluator types, status enums.

**5. Requirements approval.** The commitment screen; it should feel weightier than the rest of the
product. Major object: **the acceptance statements** — sans prose with the literal checked token
inline in mono (§8.2). This is the most under-exploited asset in the entire product: typed,
machine-checkable acceptance criteria are what nothing else has, and today they are an unstyled
nested `<details><ul>` (`Projects.tsx:258`). A requirement with no typed evaluator draws with no
notch and is labelled as not machine-verifiable — an honest weakness, shown. *Not visible:*
requirement IDs, revisions, `truth_state`, `provenance`, `source_type`, evaluator type names.

**6. Execution graph.** The meso spine is the screen. Dependency depth maps to vertical position,
so reading down is reading forward in the plan. Parallel work is visibly parallel. Interaction:
hover (desktop) or latched tap (touch, §11.5) raises a task's dependencies and dependents to full
ink and drops the rest to 25% — this is how dependency is *read*, with no arrows and no legend.
*Not visible:* every ID; route glyphs carry capability labels only.

**7. Task details.** A **side sheet**, so the lattice stays visible and the user keeps their place.
Sections: intent (sans) → effect (files changed, mono) → **acceptance, criterion by criterion,
with measured evidence** → attempts. Major object: the per-criterion result. Passed criteria carry
verified green — the only place green appears at task level. *Not visible:* run ID, attempt ID,
argv, cwd, prompt fingerprint, stdout, workspace hashes, permission profile, model route — all of
it under one control, `Technical receipt`.

**8. Attention / blocker.** §13.5. One problem, one sentence, one action, everything else at 20%.
No motion. *Not visible:* blocker codes, the blockers array, readiness JSON, route decisions,
preflight internals.

**9. Acceptance / evidence.** The gate drawn large, one segment per criterion, each labelled with
its statement and measured result. Below: the effect — files changed, with before/after hashes as
7-char mono chips. **This is the screen that proves TEMM is not lying, and it should be the screen
the product is demoed on.** *Not visible:* evaluator type names, run/attempt IDs, raw JSON, full
hashes.

**10. Deliverable.** §15.3. The emptiest screen in the product, deliberately. Major object: the
Seal. *Not visible:* deliverable ID, workspace ID, packaging internals, relative-path lists,
readiness enums. The abbreviated checksum **is** visible — it is the signature, not an internal.

**11. Dashboard / Today.** Hierarchy: *what needs me* → *what is moving* → *what finished*. Never
metrics first. Attention items at full ink, then active projects each with a 24px macro micro-rail
showing real state, then recently verified. If nothing needs the user: one line, *"Nothing needs
you. 2 projects running."* Micro-rail transit only on genuinely running projects, so the dashboard
becomes **a status board readable from across the room.**
*Not visible:* token counts, avoided cost, "Tasks today", success rate, models online, providers
connected. Those are an operator view of TEMM's own plumbing, and they currently occupy the four
largest numbers on the home screen (`Dashboard.tsx:118-121`) while the user's projects are demoted
to a "Recent runs" list — an inverted hierarchy. Also removed: the free-text task composer, which
is a second, weaker product competing with the project spine for the most valuable position in
the app.

**12. Setup / readiness — only when required.** Reached from a blocker, never volunteered. Framed
as *"this project needs X"*, never *"configure your providers"*. One action. For folder
connection: one path field, with the permission boundary stated as a promise in plain language —
*"TEMM can only read and write inside this folder."* *Not visible:* the provider registry, model
catalogue, adapter IDs, protocol versions, auth states, discovery evidence, capability matrices,
8 fleet tabs. **TEMM must not become a provider configuration dashboard.** Tools stays reachable,
competent, and never on the critical path.

---

## 18. FIRST 30 SECONDS

A cold-start user must understand the thesis in 30 seconds without reading explanatory copy,
because the product demonstrates it instead. This is the real chain, performed once — not a
simulation, not a marketing animation.

| Time | On screen | What is learned | Motion |
|---|---|---|---|
| **0–3s** | Graphite. The §7.5 motion mark draws: spine descends, cell opens, gate rule draws, cell closes. Then it holds. | *Work leaves a line and earns its way back.* Learned before a single word | 5-step chain, ≤1400ms |
| **3–8s** | One question at `--type-900`: **"What do you want finished?"** One field. No nav, no sidebar, no cards. | *I start from an outcome, not from settings* | Micro, 200ms |
| **8–14s** | The typed words settle into the goal cap at the head of the spine and stay, verbatim | *My words are the contract, not a prompt that gets discarded* | Structural, 320ms |
| **14–19s** | Requirement squares precipitate from the spine, staggered. Each carries a title and its acceptance statement | *It understood, and turned my sentence into checkable contracts.* The one permitted deliberate reveal | Chain, 420ms |
| **19–22s** | Branches draw out dashed, in dependency order. Some visibly parallel. A route glyph docks: **"Coding capability"** | *It planned real work, knows what depends on what, and needs a capability — not a brand* | Chain, 450ms |
| **22–26s** | One branch goes live: illumination travels toward the gate. An effect square materialises | *That is real work, and something real changed on disk* | Transit + 220ms |
| **26–29s** | Gate segments light in sequence, cool, across the branch. The slot opens. The branch completes through. **The spine steps up one weight. Green appears for the first time.** | *It checked its own work against my contract before claiming anything — and green means proven* | 280/criterion + 320 + 400 |
| **29–30s** | Rest. Sticky header: the goal, `Task 1 of 4 complete`, one next action | *I know where I am and what to do next* | none |

If the first task fails instead, the user learns something more valuable in the same window: TEMM
arrests at the gate, names the failed criterion, keeps the failed attempt visible, and re-routes.

---

## 19. REMOVAL CONTRACT AND PRESERVE CONTRACT

**Correction 11.** Binding during implementation.

### 19.1 REMOVAL CONTRACT — must be gone

| # | Pattern | Evidence / scope | Slice |
|---|---|---|---|
| 1 | **Tiny typography** | All 207 `font-size` declarations below 10px; all 242 below 12px. 12px floor, 8 steps | V1 |
| 2 | **Arbitrary radius values** | 147 hardcoded radii across 17 distinct values → 4 tokens | V1 |
| 3 | **Generic grey status pills** | `.status-badge` with 1 styled variant serving 9 stages and 7 task states → the §5 eleven-state system | V1–V2 |
| 4 | **Database-shaped run cards** | `RunDetails.tsx`'s five schema-named cards, rendered unconditionally at `RunWorkspace.tsx:489`; `Runs.tsx`'s 8-column grid | V6, V8 |
| 5 | **Raw enum labels** | All ~18: `lifecycle_status`, `auth_state`, `auth_method`, `health_state`, `registry_state`, `availability_state`, `cost_provenance`, `metadata_provenance`, `pricing_provenance`, `capability_provenance`, `score_provenance`, `discovery_state`, `discovery_source`, `event_type`, `executor_type`, `permission_profile`, `tool_kind`, `protocol_version` | V3, V8, V10 |
| 6 | **Default-visible full hashes** | Both 64-char SHA-256s (`FleetManager.tsx:275`, `Projects.tsx:260`) → 7-char chip, full value at L3 and on copy | V3 |
| 7 | **Large raw `<pre>` blocks** | All 6 un-collapsed of 9 (`AgentDetail.tsx:95`, `ProviderDetail.tsx:21`, `RunDetails.tsx:16`, `AutomationCenter.tsx:97`, `CommandConsole.tsx:66`, `RunWorkspace.tsx:494`) → L3 only | V3, V8 |
| 8 | **Technical IDs as hierarchy** | `adapter_id · protocol · revision` as a subtitle (`ProviderDetail.tsx:21`); `revision N` in headers (`AgentDetail.tsx:91`); `run.id` in the execution timeline (`RunWorkspace.tsx:444`); the `placeholder="run-id"` input (`AutomationCenter.tsx:97`) | V3, V8 |
| 9 | **Duplicated card containers** | `surface-card` as the universal layout (~40 uses) → L1 stations separated by rule and space, no border box, no shadow | V3 |
| 10 | **Meaningless green states** | `Dashboard.tsx:82`'s emerald "Execution route ready" derived from counting rows; every emerald badge reporting availability rather than measurement | V1, V9 |
| 11 | **Decorative animation** | `translateY(-1px)` hover lifts; the `mission-card::after` blurred gradient blob (`theme.css:236`); `.spin` on refresh; both dead visual rules `.health-orbit` (`theme.css:261`) and `.quota-meter` (`theme.css:1424`) | V1, V5 |
| 12 | **Unstyled structural project classes** | All ~12 with no CSS rule: `project-spine-workspace`, `project-progress`, `spine-next-action`, `spine-section`, `blueprint-requirements`, `spine-review-action`, `task-progress-list`, `task-progress-head`, `task-blocker`, `deliverable-row`, `readiness-blockers`, `project-readiness-card`, `project-workspace-setup` | V2–V3 |
| 13 | **Undefined CSS variables** | `--bg-card`, `--border`, `--bg-elevated` — and the invisible primary button they produce at `theme.css:144` | V1 |
| 14 | **The three-way brand collision** | lucide `Command` glyph as the mark; purple `#863bff` lightning favicon; `theme-color: #080c14` against a `#f5f6f8` canvas. Delete `public/icons.svg` (Bluesky/Discord/X in `#aa3bff`, referenced by nothing), `assets/react.svg`, `assets/vite.svg`. Fix the `index.html` title mojibake | V2 |
| 15 | **Indigo-purple as primary accent** | `#5b5ce2` — the single most generic choice in the file. Replaced by luminance-first signalling (§9.5) | V1 |
| 16 | **Operator vocabulary in user-facing copy** | "Instance state", "Measurements", "Persisted output", "Event evidence", "Fallback runs", "Unknown usage observations", "stale", "degraded", "provenance", "WebSocket open", "Interactive · PTY" | V3, V8 |
| 17 | **Infrastructure-first onboarding** | `01 DISCOVER → 02 CONNECT → 03 WORKSPACE → 04 DEFAULTS` before a goal exists | V10 |
| 18 | **Metric-first dashboard hierarchy** | Tokens / avoided cost / tasks today / tools ready as the four largest numbers (`Dashboard.tsx:118-121`); the free-text composer competing with the project spine | V9 |
| 19 | **Mono as dominant typography** | Any table, nav surface, task list or narrative set predominantly in mono (§8.2) | V1 |
| 20 | **Nav redundancy** | 10 surfaces / ~35 sub-views; run history ×4, run evidence ×3, workspace picker ×4, leaderboard ×2, skills ×2, baseline model ×3; two nav items sharing the `FolderKanban` icon (`Sidebar.tsx:31,33`) | V11 |

### 19.2 PRESERVE CONTRACT — must survive unchanged in behaviour

| # | Behaviour / asset | Why | Do not |
|---|---|---|---|
| 1 | **The spine vocabulary already in the code** | `project-spine-workspace`, `spine-next-action`, `spine-section`, `PROJECT SPINE`. The right metaphor was already chosen and never given form | Rename it |
| 2 | **The 9-value stage model and `stageCopy`** (`Projects.tsx:7-21`) | `goal → clarify → blueprint → approval → ready → running → attention → verifying → complete` is already the correct narrative and maps cleanly onto the spine | Redesign the model; give it geometry |
| 3 | **The NEXT ACTION pattern** (`Projects.tsx:254`) | One state, one sentence, one action is exactly right | Remove it — promote it to the sticky header |
| 4 | **`readinessMessage` / `readinessAction` pairing** (`Projects.tsx:175-195`) | A blocker code mapped to a human sentence *and* a specific resolving action | Replace with generic "Open setup" |
| 5 | **The capability-first copy** | "Ready to execute", "Coding capability required", "Sign in to your coding tool", "Connect project folder", "Execution blocked — action required" | Reword toward brand names |
| 6 | **The truthfulness of the copy** | "Completion is based on persisted acceptance and readiness evidence." "No acceptance-measured file has been produced yet, so there is nothing to package." "No node state is synthesized." This is the brand's actual voice and it is rare | Soften, market, or make optimistic |
| 7 | **Cross-project state-bleed guard** (`Projects.tsx:54-64`) | The `visibleProjectRef` check before every state write. A slower reload landing last could repaint one project with another's folder and readiness — an unsafe basis for dispatch | Remove during refactor |
| 8 | **Bounded settling passes on `startExecution`** (`Projects.tsx:161-164`) | One dispatch pass never reaches reconciliation, and reconciliation is what credits a measured requirement. Without this, finished work leaves an uncredited requirement and an unreachable deliverable | Reduce to a single pass |
| 9 | **Already-approved-folder resolution** (`Projects.tsx:205-209`) | Connecting a folder that is already an approved workspace resolves to it instead of failing "already registered" | Regress |
| 10 | **Acceptance-derived deliverable paths** (`Projects.tsx:226-237`) | Packaging derives paths from measured evaluators, excluding `changed_files_subset` scope clauses which say what a run was *allowed* to touch, not what exists | Revert to `['.']` |
| 11 | **Bilingual EN/AR with real RTL** | `dir=rtl`, logical properties throughout (`inset-inline-start`, `border-inline-end`), a dedicated Arabic family, per-direction letter-spacing (`theme.css:230`), forced `dir=ltr` on code/mono (`theme.css:108`). A genuine competitive asset, done properly | Use physical properties in any new work |
| 12 | **Accessibility scaffolding** | Skip link, `aria-current`, `aria-label`s, visible focus rings, `prefers-reduced-motion`, the `data-reduce-motion` preference, `accessibility.ts` | Remove — only refine reduced-motion from "zero all durations" to §6.5 |
| 13 | **The lean dependency set** | React 19, Vite 8, lucide-react, xterm, two variable fonts. Zero chart/graph/animation libraries. The lattice is orthogonal geometry with 45° chamfers — exactly the case where a graph library adds weight, licence surface and foreign visual opinions for no benefit. `prebuild` runs an Apache-2.0 licence policy check, so every dependency has real cost | Add `reactflow`, `d3`, `framer-motion`, or any charting library |
| 14 | **`LiveTerminal`** | Real xterm PTY streaming with reconnect and cancellation is hard-won | Simplify — relocate to L3 |
| 15 | **`StateNotice` as a primitive** | The right idea | Delete — reduce 8 variants to 4 with distinct geometry |
| 16 | **The theme preview cards** (`SettingsVault.tsx:259-268`) | The only genuine custom graphic in the app, and it works | Replace with a swatch |
| 17 | **The dirty working tree** | Preserved engineering state requiring explicit owner-directed cleanup in a later phase | Reset, clean, stash, discard, or commit |

---

## 20. IMPLEMENTATION FREEZE ORDER

**Correction 12.** Eleven slices. Every slice is independently shippable. **No slice depends on a
later one.** The lattice is deliberately fourth, because a lattice built on 28 font sizes and 17
radii would inherit every defect in §0.

### V1 — Tokens, typography, semantic states
*No new screens. No new components. No visual invention.*
- 8-step type scale, 12px floor; migrate all 275 declarations. Resolve the Arabic floor (12 or 13).
- 8-step spacing scale; migrate 484 hardcoded values. 4 radii; migrate 147. 4 line weights.
- Define the 3 undefined variables; fix the invisible primary button.
- Graphite-first canvas + Chalk; luminance-first signalling; the §5 eleven-state triplets.
- Bundle a mono fallback. Apply the §8 guardrails, including withdrawing mono from criterion
  statements.
- Remove decorative animation and the two dead visual rules.
- **Gates:** zero declarations below 12px · zero undefined variables · greyscale screenshot of all
  11 states, all distinguishable at 100% and 25% · §5.3 contrast pass on Graphite and Chalk ·
  `npx tsc -b` and `npm run build` pass · no page reads as monospace.

### V2 — Core primitives, the Seal, connectors
- The 7 node types (§4.1) as primitives: goal cap, requirement, task capsule, effect, gate, route
  glyph, seal. Hand-authored SVG.
- The 8 connector treatments (§4.2), including the Blocked-vs-Rejected geometric distinction.
- **The Verification Seal (§7):** open/closed pair, all six reuses, the 5-step motion mark.
  Replace the `Command` glyph, the purple favicon, and `theme-color`. Delete `icons.svg`,
  `react.svg`, `vite.svg`. Fix the title mojibake.
- Style the ~12 unstyled project classes.
- **Gates:** seal legible at 16px with the gate rule dropped · open and closed forms
  unmistakable · every primitive renders in all applicable states · EN/AR identical for the seal.

### V3 — Project Workspace, static composition
- §13 exactly: chrome, sticky Outcome, macro spine rail, collapsing stations, the Attention rule.
- Replace `surface-card` stations with rule-and-space L1 stations.
- Apply L1/L2/L3 (§10): relocate `RunDetails`, both full hashes, all 6 un-collapsed `<pre>`s, all
  ~18 enums, and the readiness JSON.
- **Gates:** the eight §13 questions answerable in ≤5s by someone who has not seen the project ·
  no tabs in the primary path · an L1-only walkthrough with zero IDs, hashes, JSON or provider
  names visible · every L3 datum reachable in ≤2 clicks.

### V4 — Work Graph
- The meso spine, static. Dependency depth → vertical position. Dependency hover-raise, plus the
  latched tap equivalent.
- The §11 matrix: full ≤24, grouped 25–80, Ledger >80, across all four viewport tiers. Attempt
  folding at 3.
- The §12 direction law throughout.
- **Gates:** correct at 1, 6, 24, 40, 120 tasks × 1600/1440/768/375 × EN/AR · no horizontal
  overflow · no type below 12px · every state also stated in text on the same screen · 44px touch
  targets in the Ledger.

### V5 — Execution motion
- The two tiers (§6.2), the chain law (§6.3), sustained transit (§6.4).
- The 20-row structural catalogue (§6.5) with its reduced-motion column.
- **The §14 first-live-execution sequence**, every step bound to a real state transition.
- **Gates:** nothing exceeds 450ms in a single movement · no chain exceeds 1400ms or 6 steps ·
  everything interruptible · ≤3 concurrent transits · reduced-motion loses no information ·
  **nothing moves unless work is in transit or the user just acted** · no step plays before its
  system fact exists · no spinner, skeleton or unmeasured progress bar anywhere.

### V6 — Acceptance and evidence
- The gate at full size, one segment per criterion with measured evidence.
- Micro spine (§3.3) in the task sheet, beside measured requirements, and in the evidence stack.
- The three failure modes (§16.3) visually distinct: Blocked · No effect · Rejected.
- Recovery: retract, parallel offset, preserved history, convergence back into the task.
- **Gates:** a genuine multi-attempt recovery is legible without opening L3 · Blocked, No effect
  and Rejected are distinguishable in greyscale · no gate is ever drawn speculatively.

### V7 — Deliverable convergence
- The §15 five-step chain and resting composition. Seal, package mark, checksum placement,
  `What was verified`.
- **Gates:** fires only when completion is evidence-based · fires once per project, never on
  re-render or navigation return · a partial project gets the Attention station instead ·
  verification and packaging are stated as separate claims · reduced-motion loses nothing.

### V8 — Supporting project screens
- Blueprint review, Requirements approval, Task details, Runs history, Evidence receipts.
- Remove the remaining database-shaped surfaces and operator vocabulary.
- **Gates:** the acceptance statements are the dominant object on the Requirements screen and are
  set in sans with inline mono tokens · no schema-named heading survives.

### V9 — Dashboard / Today
- Attention-first hierarchy. Macro micro-rails per project. Remove the metric-first block and the
  free-text composer.
- **Gates:** readable as a status board at 2m distance · no unearned green · no operator metric in
  the primary hierarchy.

### V10 — Setup / readiness
- Blocker-triggered, project-framed, one action. Replace the infrastructure-first onboarding with
  the §18 sequence.
- **Gates:** a new user reaches a created project without seeing a provider, model, adapter or
  auth state · a user who has never seen TEMM can state what it does after 30 seconds with no
  explanatory copy.

### V11 — Navigation consolidation
*Last, because it is the most disruptive and needs everything above to be true first.*
- 10 surfaces → **Today · Projects · Tools · Settings.** Everything else becomes disclosure inside
  a project. Resolve run history ×4, run evidence ×3, workspace picker ×4, leaderboard ×2,
  skills ×2, baseline model ×3.
- **Gates:** no concept reachable from more than one top-level surface · nothing became
  unreachable · no two nav items share an icon.

### Cross-cutting gates — every slice
- `npx tsc -b` and `npm run build` pass.
- **849 backend tests remain green. No Core change is made for a visual slice.**
- EN and AR verified at 1600 / 1440 / 768 / 375, no horizontal overflow.
- Greyscale legibility verified. Reduced-motion verified. Nothing below 12px.
- **No green pixel that was not earned by measured acceptance.**
- No new runtime dependency without an Apache-2.0-compatible licence check.
- The dirty working tree preserved; nothing reset, cleaned, stashed, committed or pushed.

### Two acknowledged risks

1. **Bespoke visual grammar has a maintenance cost.** A hand-authored lattice diverges from every
   off-the-shelf design system. Mitigation: the grammar is deliberately small — 7 nodes, 8
   connectors, 4 radii, 8 type steps, 4 line weights, 11 states, 3 scales — it ships as tokens
   before pixels (V1 before V4), and the lattice is never the only readout, so a regression in it
   degrades rather than blocks.
2. **The metaphor has a learning cost.** Mitigation: §18 teaches it in 3 seconds before any UI
   exists; §3's containment law stops it becoming wallpaper; and §10's rule that every graphical
   state is simultaneously stated in text means the product is fully usable by someone who never
   learns the grammar.

---

## 21. UNRESOLVED CREATIVE QUESTIONS

Four questions this freeze does not settle. None blocks V1. Each has a named slice by which it
must be decided.

| # | Question | Options | Decide by |
|---|---|---|---|
| 1 | **Sans family.** Manrope is installed and acceptable but slightly soft for the instrument reference class. Swap, or commit? | (a) Keep Manrope — zero cost, slightly generic. (b) Swap to a tighter grotesque with stronger tabular numerals — better fit, one dependency and one licence check | **V8** (V1–V3 are safe on Manrope; the scale is family-independent) |
| 2 | **The Arabic type floor.** 12px may be too small for Alexandria at label sizes; Arabic generally reads one step larger | (a) Global 12px floor, accept slightly tight Arabic. (b) Per-locale floor: 12px LTR, 13px RTL — correct, but two scales to maintain | **V1** — must be empirical, tested with an Arabic reader, not chosen on theory |
| 3 | **Exact hue values.** The freeze fixes the *policy* (green earned, clay not red, luminance-first, warm live / cool verifying) but not the values. Getting warm-live away from Grafana amber and clay away from alarm red is a calibration exercise on real Graphite | Requires side-by-side calibration against the reference class at §5.3 contrast, in both modes | **V1** — the last thing in V1, after the structural work proves the states are legible without hue |
| 4 | **Lattice orientation at wide desktop.** ≥1600px yields lateral room the vertical lattice does not spend. Use it for branch travel, or for a persistent task sheet? | (a) Wider branch travel — more dramatic, more eye movement. (b) Persistent side sheet (current §11.1 recommendation) — more useful, less spectacular. (c) Both, user-toggled — most flexible, two layouts to maintain | **V4** — needs a real 40-task project to judge honestly |

Two questions deliberately **closed** in this freeze, recorded so they are not reopened without
cause:

- **Should the seal have a mirrored RTL variant?** No. It is vertically symmetric about its own
  spine and is identical in every locale (§12.2).
- **Should the deliverable convergence be longer / full-screen?** No. 1400ms, five steps, in
  place. The reward is reduction, not spectacle (§15.2).

---

## APPENDIX — THE FROZEN DIRECTION IN ONE PARAGRAPH

TEMM is instrumentation, not decoration. A single **spine** carries verified progress at three
contained scales — **macro** lifecycle, **meso** work graph, **micro** verification receipt — and
appears nowhere outside a project. Work leaves the spine as a **branch** and cannot rejoin without
measured acceptance evidence, so the visual rule *is* the engineering rule. Runs are lengths of
line, not cards; attempts are parallel offset segments so recovery stays visible; acceptance is a
**gate** whose segments light one per typed criterion; and the three honest failure modes —
**blocked** before the gate, **no effect** unable to reach it, **rejected** flush against it — are
geometrically distinct. Eleven semantic states each differ in at least two of geometry, line, fill
and position, so the product is legible in greyscale. Motion has two tiers — **micro 120–220ms**,
**structural 280–450ms** — chained to at most 1400ms, never cinematic, permitted only for work in
transit or the direct consequence of a user action, so movement is diagnostic. Canvas is
graphite, signalling is luminance-first, and **green appears only when something was measured and
accepted** — green is earned. **Monospace is machine-measured fact and appears inline only**;
sans carries every narrative, table, task and navigation label. The **Verification Seal** is the
closed cell: two branches that departed the spine, passed a gate, and converged — an open form
that verification literally closes, reusable as seal, motif, motion mark, icon, favicon and a
chain-of-evidence package mark. The workspace is one continuous spine of stations that collapse as
they settle, so the screen physically shortens as the project converges, and a blocker preempts
everything at 20% ink. The closing image is the thesis: many thin uncertain dashed lines become
one thick certain line and a seal — **the end state is simpler than the start.**

---

**DESIGN FREEZE READY. No code was written or modified. First implementation slice is V1 —
tokens, typography, semantic states.**

