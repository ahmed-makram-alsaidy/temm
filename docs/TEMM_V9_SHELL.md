# TEMM V9 — Global Product Shell + Navigation Identity

**Status:** production. V9 converges the application frame — sidebar, topbar,
navigation hierarchy, system status — onto the frozen V1–V8 vocabulary. Inner
legacy pages (Tools, Settings, Insights, …) keep their own styles; the shell
now frames them as one product.

## Shell hierarchy

**Sidebar** (the product map):
- **Primary work** (unlabeled group, first): **Projects** — the flagship — and
  **Runs**. These are where outcomes live.
- **System** (labeled group): Workspaces, Command console, Tools, Skills &
  workflows, Insights, Model lab, System overview (the operator dashboard,
  renamed from "Home" and demoted from the top of the list to its honest
  place).
- **Footer**: Settings, then the execution-readiness line.

Nothing was removed and nothing invented: every route App.tsx renders is in
the model (`shell-navigation.ts`), one-to-one, proven by test.

**Header**: location only. The brand kicker renders on mobile (where the
sidebar is hidden) and is hidden on desktop — the sidebar owns the brand.
Global search (`/`), theme, language, tool-scan, and refresh are preserved,
restyled quiet.

## Active-location semantics

`activeTab` in App.tsx remains the single routing truth (remembered surface
still wins; Projects is the fallback default). The sidebar derives active
state through `surfaceIsActive()`, so an **open run detail keeps Runs marked
current**. Selection renders as **location, not acceptance**: object
background, ink-max text, a 3px inline-start marker bar, `aria-current="page"`,
and a direction-aware chevron — never a hue, never earned green.

## Color semantics in the shell

| Treatment | Truth | Meaning |
|---|---|---|
| Ink/object + marker bar | `activeTab` | you are here |
| Neutral ink "Ready" | `fleet_counts.execution_ready === true` | execution readiness — operational, not acceptance |
| Clay "Setup needed" | `execution_ready !== true` | attention: setup required |
| Ink-filled button | — | the one primary action (New project) |

The legacy emerald "Ready to run" glow, pulsing cyan dot, violet accent
selection, and the Tools online-models count pill are gone. No shell
animation exists (`check:v9` forbids keyframes/animation/infinite in
shell.css).

## Typography

All shell text sits on the frozen `--type-*` scale: nav items and search at
`--type-300` (13px), labels/status/meta at `--type-200` (12px), page name at
`--type-400`. The 8–11.5px legacy shell text is gone; the gate forbids raw px
font sizes in shell.css.

## Files

- `apps/web/src/components/shell-navigation.ts` — the single nav model.
- `apps/web/src/components/Sidebar.tsx`, `Header.tsx` — regrouped, restyled.
- `apps/web/src/components/shell.css` — shell-scoped TEMM restyle (imported
  after theme.css; inner pages untouched).
- `apps/web/src/App.tsx` — shell.css import only.
- `apps/web/src/__tests__/shell-navigation.test.ts` — 6 truth tests.
- `tools_web/check_v9_shell.py`, `tools_web/capture_v9_shell.py`.

## Verification

```text
# from apps/web
npm run test:v9
npm run check:v9
# from the repository root (real backend on :8787)
python tools_web/capture_v9_shell.py
```

Real-product captures (`docs/specimen-v9/`): cold launch (Projects current),
Runs, an open run detail (Runs stays current), Tools, Settings, back to
Projects, RTL Runs, mobile closed + drawer. Each shot asserts the active
route, `aria-current`, both groups, the status tone, the 12px shell floor,
and no horizontal overflow.

## Known remaining legacy inner surfaces

Tools, Settings, Insights, Model lab, Automation, Workspaces, Console, and
the Dashboard keep their pre-V9 inner styling. The frame is TEMM; those
interiors belong to later slices. The Dashboard's operator metrics remain
inside that surface only — the shell does not aggregate or score them.
