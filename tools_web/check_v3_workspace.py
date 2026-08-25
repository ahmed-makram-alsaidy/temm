"""Static contract checks for the V3 Project Workspace."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
COMPONENTS = WEB / "src" / "components"
MODEL = COMPONENTS / "project-workspace-model.ts"
COMPONENT = COMPONENTS / "ProjectWorkspace.tsx"
INTEGRATION = COMPONENTS / "Projects.tsx"
CSS = COMPONENTS / "project-workspace.css"
TOKENS = WEB / "src" / "styles" / "tokens.css"
SPECIMEN = WEB / "src" / "specimens" / "V3WorkspaceSpecimen.tsx"
ENTRY = WEB / "src" / "v3-specimen.tsx"
HTML = WEB / "specimen" / "v3.html"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [MODEL, COMPONENT, INTEGRATION, CSS, TOKENS, SPECIMEN, ENTRY, HTML]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    model = MODEL.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")
    integration = INTEGRATION.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    tokens = TOKENS.read_text(encoding="utf-8")
    specimen = SPECIMEN.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    exports = [
        "export const TASK_SCALE_THRESHOLDS",
        "export interface ProjectWorkspaceModel",
        "export function directionFor",
        "export function selectTaskScale",
        "export function deriveProjectWorkspaceModel",
    ]
    for item in exports:
        require(item in model, f"model contract missing: {item}")
    require("latticeMax: 24" in model and "groupedMax: 80" in model, "task scale thresholds changed")
    require("criterionIsMeasured" in model, "measured-evidence guard is missing")
    require("input.completion?.ready" in model, "completion readiness is not consulted")
    require("deliverable.readiness === 'ready'" in model, "ready persisted package guard is missing")
    require("attention.action ?" in model, "attention still assumes every blocker has a resolver")

    primitives = ["ExecutionNode", "ExecutionConnector", "AcceptanceGate", "StatusPrimitive", "ClosedCell"]
    for primitive in primitives:
        require(primitive in component, f"workspace does not consume V2 primitive: {primitive}")
    require("data-v3-primary=\"true\"" in component, "primary action marker is missing")
    require("location === 'attention'" in component and "location === 'delivery'" in component, "primary action locations are not mutually routed")
    require("dir={model.direction}" in component, "workspace direction is not explicit")
    require("data-project-question" in component, "clarification inputs are not preserved")
    require("Technical receipt" in component, "technical receipts are not reachable")

    require("deriveProjectWorkspaceModel" in integration, "production Projects surface does not use the V3 model")
    require("<ProjectWorkspace" in integration, "production Projects surface does not render V3")
    for action in [
        "understand-goal", "save-clarifications", "approve-blueprint", "approve-requirements",
        "compile-plan", "connect-workspace", "open-tools", "start-execution",
        "continue-execution", "package-deliverable",
    ]:
        require(f"'{action}'" in integration, f"production action is not routed: {action}")
    require("visibleProjectRef.current !== project.id" in integration, "stale project reload guard is missing")
    require("for (let pass = 0; pass < 6" in integration, "bounded dispatch settling changed")

    defined_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    used_tokens = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    # Component-scoped state custom props (set from TSX or by the V7 chain
    # choreography), not V1 semantic tokens.
    component_state = {"--v3-depth", "--v7-row", "--v7-converge-x"}
    unknown_tokens = used_tokens - defined_tokens - component_state
    require(not unknown_tokens, f"workspace CSS uses undefined V1 tokens: {sorted(unknown_tokens)}")
    require("--temm-color" not in css and "--temm-spacing" not in css, "workspace CSS uses rejected placeholder tokens")
    require("@media (max-width: 820px)" in css and ".temm-v3-mobile-ledger" in css, "mobile ledger contract is missing")
    require("[dir='rtl']" in css, "RTL-specific typography treatment is missing")
    require(not re.search(r"font-size\s*:\s*\d", css), "workspace CSS bypasses the V1 type scale")

    combined = model + component + integration + css + specimen + entry
    require(not re.search(r"#[0-9a-fA-F]{3,8}\b", combined), "V3 code contains a magic color")
    require("scaleX" not in combined, "V3 mechanically mirrors RTL")
    require("infinite" not in css, "V3 CSS contains an idle loop")
    require(not re.search(r"\b(?:spinner|shimmer|progress-bar)\b", combined, re.IGNORECASE), "V3 fabricates progress")

    for state in ["ready", "live", "attention", "verified", "empty"]:
        require(f"'{state}'" in specimen, f"specimen state is missing: {state}")
    require("deriveProjectWorkspaceModel" in specimen, "specimen bypasses the production adapter")
    require("data-theme" in html and "/src/v3-specimen.tsx" in html, "specimen HTML entry is invalid")
    require("document.documentElement.dir" in entry, "specimen does not exercise document direction")

    print("V3 WORKSPACE CONTRACT PASSED")
    print(f"files={len(paths)} primitives={len(primitives)} tokens={len(used_tokens)}")


if __name__ == "__main__":
    main()
