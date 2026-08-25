"""Static contract checks for the V2 execution primitive system."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ROOT / "apps" / "web" / "src" / "components" / "visual-primitives"
TSX = (PRIMITIVES / "ExecutionPrimitives.tsx").read_text(encoding="utf-8")
TYPES = (PRIMITIVES / "execution-types.ts").read_text(encoding="utf-8")
CSS = (PRIMITIVES / "execution-primitives.css").read_text(encoding="utf-8")
MOTION = (PRIMITIVES / "execution-motion.css").read_text(encoding="utf-8")
INDEX = (PRIMITIVES / "index.ts").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    components = {
        "ClosedCell",
        "EvidencePackage",
        "AcceptanceGate",
        "ExecutionConnector",
        "FailureGeometry",
        "AttemptHistory",
        "StatusPrimitive",
        "ExecutionNode",
        "ExecutionStation",
    }
    for component in components:
        require(f"export function {component}" in TSX, f"missing component: {component}")
        require(component in INDEX, f"missing public export: {component}")

    states = {
        "neutral", "planned", "ready", "running", "attention", "blocked",
        "retrying", "verifying", "rejected", "accepted", "complete",
    }
    for state in states:
        require(f"'{state}'" in TYPES, f"missing semantic state: {state}")

    connectors = {"planned", "ready", "running", "retry", "blocked", "effect", "rejected", "accepted"}
    for connector in connectors:
        require(f"| '{connector}'" in TYPES or f"=\n  '{connector}'" in TYPES, f"missing connector: {connector}")

    require("M12 4 L19 11 L19 15 L14.5 19.5" in TSX, "open cell must retain the full silhouette")
    require("L5 15 L9.5 19.5" in TSX, "open cell must leave the bottom vertex unjoined")
    require("16: 1.85" in TSX and "64: 1.1" in TSX, "optical cell weights changed")
    require("size >= 20" in TSX, "the 16px gate-detail drop is missing")
    require("state !== 'dormant'" in TSX, "dormant gate must remain absent")
    require("criteria.map" in TSX, "gate criteria must remain variable-N")
    # The full acceptance gate (the contract) must draw every criterion. The
    # V6 micro spine is a receipt GLYPH at reading size: it may compress the
    # drawn segments, but only if the true count stays in its accessible label
    # and the untruncated gate remains the variable-N authority.
    gate_body = TSX[TSX.index("export function AcceptanceGate"):TSX.index("export function MicroSpine")] if "export function MicroSpine" in TSX else TSX[TSX.index("export function AcceptanceGate"):]
    require("criteria.slice" not in gate_body, "the acceptance gate truncated its criteria")
    micro_body = TSX[TSX.index("export function MicroSpine"):] if "export function MicroSpine" in TSX else ""
    if micro_body:
        require("criteria.length" in micro_body, "the micro spine must carry the true criterion count in its label")
    require("direction === 'rtl' ? width - lead : lead" in TSX, "RTL must use explicit logical coordinates")

    combined = TSX + CSS
    require(not re.search(r"#[0-9a-fA-F]{3,8}\b", combined), "primitive code contains a magic color")
    require(not re.search(r"\b\d+(?:\.\d+)?ms\b", combined), "primitive code contains a hardcoded motion duration")
    require("scaleX" not in combined + MOTION, "primitive code mechanically mirrors RTL")
    require("infinite" not in CSS, "primitive CSS contains an idle loop")
    # V5 amendment: the ONE sanctioned continuous motion is the sustained causal
    # transit in execution-motion.css. It must remain the only infinite loop in
    # the primitive layer, must consume the V1 transit token, and must be
    # explicitly disabled under both reduced-motion channels.
    motion_loops = re.findall(r"animation:[^;]*infinite", MOTION)
    require(len(motion_loops) == 1 and "temm-transit-travel" in motion_loops[0] and "--transit-cycle" in motion_loops[0],
            "primitive motion layer must contain exactly the sanctioned transit loop")
    require(MOTION.count("@keyframes") >= 1 and "temm-transit-travel" in MOTION, "transit keyframes missing")
    reduced_block = MOTION[re.search(r"@media \(prefers-reduced-motion", MOTION).start():] if "@media (prefers-reduced-motion" in MOTION else ""
    require("animation: none" in reduced_block and ".temm-connector__transit" in reduced_block,
            "transit must be disabled under prefers-reduced-motion")
    require(re.search(r":root\[data-reduce-motion='true'\] \.temm-connector__transit \{ animation: none", MOTION),
            "transit must be disabled under the explicit reduce-motion preference")
    require(not re.search(r"#[0-9a-fA-F]{3,8}\b", MOTION), "motion CSS contains a magic color")
    require(not re.search(r"\b\d+(?:\.\d+)?ms\b", MOTION), "motion CSS contains a hardcoded motion duration")
    require(not re.search(r"\bd=\{?['\"][^'\"]*[CQAS]", TSX), "primitive SVG contains a curved path command")

    required_tokens = {
        "--mark-stroke-open", "--mark-stroke-closed", "--mark-gate-earned",
        "--state-running", "--state-verifying", "--state-rejected",
        "--state-accepted", "--state-complete", "--t-struct", "--e-out",
    }
    for token in required_tokens:
        require(token in CSS, f"primitive CSS does not consume {token}")

    print("V2 PRIMITIVE CONTRACT PASSED")
    print(f"components={len(components)} states={len(states)} connectors={len(connectors)}")


if __name__ == "__main__":
    main()
