"""Static contract checks for the V7 deliverable convergence."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
MOTION = WEB / "src" / "components" / "project-workspace-motion.ts"
COMPONENT = WEB / "src" / "components" / "ProjectWorkspace.tsx"
PRIMITIVES_TSX = WEB / "src" / "components" / "visual-primitives" / "ExecutionPrimitives.tsx"
TYPES = WEB / "src" / "components" / "visual-primitives" / "execution-types.ts"
WORKSPACE_CSS = WEB / "src" / "components" / "project-workspace.css"
TEST = WEB / "src" / "__tests__" / "project-convergence.test.ts"
SPECIMEN = WEB / "src" / "specimens" / "V5MotionLabSpecimen.tsx"
PACKAGE = WEB / "package.json"
CAPTURE = ROOT / "tools_web" / "capture_v7_convergence.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [MOTION, COMPONENT, PRIMITIVES_TSX, TYPES, WORKSPACE_CSS, TEST, SPECIMEN, PACKAGE, CAPTURE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    motion = MOTION.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")
    primitives = PRIMITIVES_TSX.read_text(encoding="utf-8")
    types = TYPES.read_text(encoding="utf-8")
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    specimen = SPECIMEN.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    # Canonical completion truth (freeze §15.1): `evidence.verified` is a
    # presentation alias of backend `completion.ready` — never an independent
    # calculation from accepted tasks, evidence counts, artifacts, or gates.
    # The alias line must exist verbatim in the adapter so no task-count or
    # gate heuristic can replace it without failing this gate.
    model_src = (WEB / "src" / "components" / "project-workspace-model.ts").read_text(encoding="utf-8")
    require("verified: input.completion?.ready === true," in model_src,
            "evidence.verified must remain the direct projection of canonical completion.ready")

    # Controller: the only project-level event, transition-only, suppressed
    # under reduced motion, never on initial load.
    require("export type ProjectMotionEvent = 'project-verified'" in motion, "the convergence event is missing from the controller")
    require("options.allowMotion !== false && !previous.evidence.verified && next.evidence.verified" in motion,
            "the event must fire only on the observed transition with motion allowed")
    require("projectEvents: []" in motion, "initial load and null models must settle without the event")

    # Component: transient chain state, once per observed verification.
    require("data-convergence={converging ? 'true' : undefined}" in component, "the chain state is not attached to the workspace")
    require("setConverging(true)" in component and "setConverging(false), 2100" in component, "the chain must end and hand over to the resting composition")
    require("projectEvents.includes('project-verified')" in component, "the chain is not driven by the controller event")
    require("model.evidence.verified && converging && model.work.scale === 'lattice'" in component,
            "the transient lattice must be lattice-scale only")
    require("temm-v3-retired-work" in component, "the resting work record is missing")

    # Resting composition (freeze §15.3).
    require("temm-v7-resting" in component and "temm-v7-seal" in component and "temm-v7-receipt" in component, "the resting composition is incomplete")
    require("state=\"closed\"" in component and "size={128}" in component, "the seal is not the deliverable-scale Closed Cell")
    require("animate={converging}" in component, "the seal does not close as chain step 5")
    require("What was verified" in component, "the verification disclosure is missing")
    require("EvidencePackage" in component, "the package verification mark is missing")
    require("Verification and packaging are separate claims" in component, "the packaging limitation sentence is missing")

    # Seal sizes extend the optical curve.
    require("'open' | 'closed'" in types and "96 | 128" in types, "the deliverable seal sizes are missing")
    require("96: 1.02" in primitives and "128: 0.98" in primitives, "the seal optical weights are missing")

    # Chain choreography: five steps, frozen offsets, finite.
    require(css.count("@keyframes temm-evidence-converge") == 1 and css.count("@keyframes temm-branch-retire") == 1 and css.count("@keyframes temm-anchor-materialise") == 1,
            "chain keyframes are missing or duplicated")
    for offset in ["180ms", "480ms", "840ms", "1160ms", "1320ms"]:
        require(offset in css, f"chain offset missing: {offset}")
    require("animation-delay: calc(180ms + var(--v7-row, 0) * 40ms)" in css, "the gate stagger is not dependency-ordered")
    require("--v7-converge-x: -32px" in css and "--v7-converge-x: 32px" in css, "evidence departure ignores direction")
    require("[dir='rtl'] .temm-v3-workspace[data-convergence='true'] { --v7-converge-x: 32px; }" in css, "RTL convergence departure is missing")
    require("infinite" not in css, "V7 introduced an idle loop")
    require(not re.search(r"font-size\s*:\s*\d", css), "V7 bypasses the V1 type scale")
    require("var(--role-signature)" in css, "the deliverable name does not use the signature role")
    reduced = css[css.index("Reduced motion removes the entire chain"):]
    require("animation: none" in reduced and ".temm-cell__lower" in reduced, "reduced-motion must kill the whole chain in CSS")
    require("var(--t-struct)" in css and "var(--e-out)" in css, "the chain must consume V1 motion tokens")

    combined = motion + component + specimen + test
    require("scaleX" not in combined, "V7 mechanically mirrors RTL")
    require(not re.search(r"\b(?:spinner|shimmer|progress-bar)\b", combined, re.IGNORECASE), "V7 fabricates progress")
    require("setInterval" not in combined and "requestAnimationFrame" not in combined, "V7 must not run JS animation loops")

    require('"test:v7"' in package and '"check:v7"' in package, "V7 verification scripts are missing")
    require("'convergence'" in specimen, "the motion lab lacks the convergence scenario")

    for phrase in [
        "the convergence event fires on the observed verification transition",
        "an already-verified project never replays the convergence on load",
        "reduced motion never emits the convergence event",
        "a hidden tab absorbs the verification without replaying the chain",
        "the same snapshot twice never refires the convergence",
        "canonical completion alone drives the chain — nothing else has to change",
        "unverified work can never converge, whatever the task states claim",
        "the resting receipt is fed by measured facts only",
        "verification and packaging stay separate claims in the resting model",
    ]:
        require(phrase in test, f"V7 truth test missing: {phrase}")

    print("V7 DELIVERABLE CONVERGENCE CONTRACT PASSED")
    print(f"files={len(paths)} chain_steps=5 convergence_tests=9")


if __name__ == "__main__":
    main()
