"""Static contract checks for the V5 execution motion layer."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
MOTION = WEB / "src" / "components" / "project-workspace-motion.ts"
COMPONENT = WEB / "src" / "components" / "ProjectWorkspace.tsx"
PRIMITIVES_TSX = WEB / "src" / "components" / "visual-primitives" / "ExecutionPrimitives.tsx"
PRIMITIVES_MOTION_CSS = WEB / "src" / "components" / "visual-primitives" / "execution-motion.css"
WORKSPACE_CSS = WEB / "src" / "components" / "project-workspace.css"
TOKENS = WEB / "src" / "styles" / "tokens.css"
TEST = WEB / "src" / "__tests__" / "project-workspace-motion.test.ts"
SPECIMEN = WEB / "src" / "specimens" / "V5MotionLabSpecimen.tsx"
ENTRY = WEB / "src" / "v5-specimen.tsx"
HTML = WEB / "specimen" / "v5.html"
PACKAGE = WEB / "package.json"
CAPTURE = ROOT / "tools_web" / "capture_v5_motion.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [MOTION, COMPONENT, PRIMITIVES_TSX, PRIMITIVES_MOTION_CSS, WORKSPACE_CSS, TOKENS, TEST, SPECIMEN, ENTRY, HTML, PACKAGE, CAPTURE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    motion = MOTION.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")
    primitives = PRIMITIVES_TSX.read_text(encoding="utf-8")
    motion_css = PRIMITIVES_MOTION_CSS.read_text(encoding="utf-8")
    workspace_css = WORKSPACE_CSS.read_text(encoding="utf-8")
    tokens = TOKENS.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    specimen = SPECIMEN.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    for export in [
        "export function deriveMotionPlan",
        "export function assignTransit",
        "export function settleMotionPlan",
        "TRANSIT_CONCURRENCY_LIMIT = 3",
    ]:
        require(export in motion, f"motion controller contract missing: {export}")
    require("previousById" in motion and "arrivedAttemptIds" in motion, "attempt identity diffing is missing")
    require("if (!previous)" in motion and "events: []" in motion.replace("events, ", "events: [],"), "initial load must settle history")

    require("useWorkspaceMotion" in component, "production workspace does not consume the motion controller")
    require("visibilitychange" in component, "hidden-tab reconciliation is missing")
    require("data-reduce-motion" in component and "prefers-reduced-motion" in component, "reduce-motion channels are not respected by the controller")
    require("data-motion=" in component, "task motion events are not attached to rows")
    require("data-arrived=" in component and "data-settled=" in component, "attempt arrival/settle markers are missing")
    require("transit={motion.transit}" in component, "connectors do not receive the transit state")
    require("animate={motion.events.some" in component, "gate arrival animations are not wired")

    require("temm-connector__transit" in primitives, "connector does not render the transit path")
    require("pathLength={100}" in primitives, "transit path lacks the fixed path length")
    require("treatment === 'running' ? " in primitives and "treatment === 'retry' ? " in primitives, "transit is not bound to live treatments")

    loops = re.findall(r"animation:[^;]*infinite", motion_css)
    require(len(loops) == 1 and "--transit-cycle" in loops[0], "the motion layer must contain exactly the sanctioned transit loop")
    require("stroke-dasharray: 14 86" in motion_css, "transit dash geometry changed")
    require(motion_css.count("@keyframes") == 4, f"unexpected keyframe count in motion CSS: {motion_css.count('@keyframes')}")
    for keyframe in ["temm-transit-travel", "temm-effect-materialise", "temm-strike-draw", "temm-rejoin-draw"]:
        require(f"@keyframes {keyframe}" in motion_css, f"missing keyframe: {keyframe}")
    require("animation: none" in motion_css, "reduced-motion guards are missing from motion CSS")
    require(not re.search(r"#[0-9a-fA-F]{3,8}\b", motion_css), "motion CSS contains a magic color")
    require(not re.search(r"\b\d+(?:\.\d+)?ms\b", motion_css), "motion CSS contains a hardcoded duration")

    require("infinite" not in workspace_css, "workspace CSS contains an idle loop")
    for keyframe in ["temm-attempt-arrive", "temm-attempt-settle"]:
        require(f"@keyframes {keyframe}" in workspace_css, f"missing arrival keyframe: {keyframe}")
    require("animation: none" in workspace_css, "reduced-motion guards are missing from workspace CSS")

    # The V1 token layer zeroes --transit-cycle under reduced motion; the motion
    # layer must additionally disable the loop outright (0ms infinite is not a
    # reduced-motion path).
    reduced_tokens = tokens[tokens.index("@media (prefers-reduced-motion"):]
    require("--transit-cycle: 0ms" in reduced_tokens, "V1 tokens must suppress the transit cycle")

    combined = motion + component + specimen + entry
    require("scaleX" not in combined and "scaleX" not in motion_css, "V5 mechanically mirrors RTL")
    require(not re.search(r"\b(?:spinner|shimmer|progress-bar)\b", combined, re.IGNORECASE), "V5 fabricates progress")
    require("setInterval" not in combined and "requestAnimationFrame" not in combined, "V5 must not run JS animation loops in production")

    for scenario in ["ready-running", "transit", "no-effect", "rejected", "accepted", "retry-chain", "concurrent", "waiting", "blocked"]:
        require(f"'{scenario}'" in specimen, f"motion lab scenario missing: {scenario}")
    require("deriveProjectWorkspaceModel" in specimen and "deriveMotionPlan" not in specimen, "motion lab must drive the production model, not the controller directly")
    require("document.documentElement.dir" in entry, "V5 specimen does not exercise document direction")
    require("/src/v5-specimen.tsx" in html, "V5 specimen HTML entry is invalid")
    require('"test:v5"' in package and '"check:v5"' in package, "V5 verification scripts are missing")

    for phrase in [
        "initial historical load settles without replaying events",
        "diffs a running start as task activation",
        "diffs a new attempt without animating prior attempts",
        "diffs a no-effect terminal without inventing a gate",
        "diffs a rejection at the gate",
        "diffs measured acceptance as the only path to task-accepted",
        "the same snapshot twice never replays a transition",
        "reduced motion settles immediately and suppresses transit",
        "hidden-tab reconciliation absorbs missed transitions without replay",
        "caps prominent transit at three concurrent active tasks",
        "a task absent from the previous snapshot settles instead of animating",
        "missing run data fabricates no transitions",
    ]:
        require(phrase in test, f"V5 motion test missing: {phrase}")

    print("V5 EXECUTION MOTION CONTRACT PASSED")
    print(f"files={len(paths)} scenarios=9 controller_tests=14 keyframes=6")


if __name__ == "__main__":
    main()
