# TEMM V2 - Closed Cell + Core Execution Primitives

**Status:** production primitive API. The implementation lives in
`apps/web/src/components/visual-primitives/`. It is intentionally not composed
into the Project Workspace; that is V3.

## Public API

Import from `components/visual-primitives`:

| Primitive | Purpose |
|---|---|
| `ClosedCell` | Canonical open/closed verification geometry at 16, 24, 40, or 64px |
| `EvidencePackage` | Three cells on one spine; accepts `verifiedCount` 0-3 |
| `ExecutionNode` | Task, run, attempt, effect, gate, evidence, or convergence glyph |
| `ExecutionConnector` | Planned, ready, running, retry, blocked, effect, rejected, or accepted line treatment |
| `FailureGeometry` | Direct Blocked / No Effect / Rejected comparison |
| `AttemptHistory` | Three retained attempts, including a separate compact composition |
| `AcceptanceGate` | Dormant, evaluating, rejected, and accepted gate states; variable criterion count |
| `StatusPrimitive` | The frozen eleven-state visual and text primitive |
| `ExecutionStation` | Macro / meso / micro containment structure; draws no duplicate semantic spine |

All directional primitives accept `direction="ltr" | "rtl"`. Coordinates are
resolved from the logical leading edge; no primitive uses CSS mirroring.
Their named construction spaces are fixed SVG `viewBox` units: CSS resizing
scales the whole grammar without decoupling gates, effects, and connectors.

## Closed Cell

The component uses the frozen 24-unit construction. The open form draws both
sides of the closed silhouette but leaves the bottom vertex unjoined at
`(14.5,19.5)` and `(9.5,19.5)`. This avoids the arrow reading found in the
prototype. The closed form joins at `(12,22)` and adds the measured gate at
`y=15`.

Optical grid-unit weights are `1.85 / 1.52 / 1.25 / 1.1` at
`16 / 24 / 40 / 64px`. At 16px the gate rule is dropped; the silhouette and
overrunning spine remain. Only a closed, measured cell may draw
`--mark-gate-earned`.

## Failure Geometry

- **Blocked:** short run ending bluntly, visible dependency gap, no effect
  socket, no gate or gate-like cap.
- **No Effect:** full run into an outlined empty effect socket, no gate.
- **Rejected:** filled effect, branch flush at a closed gate, failed gate struck.

The three outcomes differ by run extent, socket presence/fill, gate presence,
and structural interruption. Color is supplementary.

## State And Motion Law

`StatusPrimitive` supports all eleven frozen states. Labels are mandatory in
the public component, and Accepted / Complete use different position and line
geometry. Primitive CSS consumes only V1 semantic tokens.

V2 includes one optional, user-triggered Closed Cell transition. It consumes
V1 structural timing and has no idle loop. Under `prefers-reduced-motion` or
`data-reduce-motion='true'`, the final state renders immediately. Sustained
execution travel remains V5.

## Development Proof

Run the Vite app and open `/specimen/v2.html`. Query controls support:

- `theme=light`
- `grey=1`
- `rtl=1`
- `reduced=1`
- `compact=1`
- `focus=cell|failures|attempt`

Verification tools:

```text
python tools_web/check_v2_primitives.py
python tools_web/capture_v2_specimen.py
```

The capture harness writes reviewed artifacts to `docs/specimen-v2/`.
