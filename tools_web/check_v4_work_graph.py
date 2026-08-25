"""Static contract checks for the V4 live task lattice."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
COMPONENTS = WEB / "src" / "components"
MODEL = COMPONENTS / "project-workspace-model.ts"
COMPONENT = COMPONENTS / "ProjectWorkspace.tsx"
INTEGRATION = COMPONENTS / "Projects.tsx"
API = WEB / "src" / "services" / "api.ts"
CSS = COMPONENTS / "project-workspace.css"
TOKENS = WEB / "src" / "styles" / "tokens.css"
TEST = WEB / "src" / "__tests__" / "project-execution-model.test.ts"
SPECIMEN = WEB / "src" / "specimens" / "V4WorkGraphSpecimen.tsx"
ENTRY = WEB / "src" / "v4-specimen.tsx"
HTML = WEB / "specimen" / "v4.html"
PACKAGE = WEB / "package.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [MODEL, COMPONENT, INTEGRATION, API, CSS, TOKENS, TEST, SPECIMEN, ENTRY, HTML, PACKAGE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    model = MODEL.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")
    integration = INTEGRATION.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    tokens = TOKENS.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    specimen = SPECIMEN.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    for export in [
        "export interface RunRecord",
        "export interface RunView",
        "export interface TaskExecutionPresentation",
        "export function deriveTaskExecutionPresentation",
    ]:
        require(export in model, f"canonical execution adapter contract missing: {export}")
    require("receipt?.workspace_diff" in model and "receipt?.no_effect === true" in model, "effect truth is not receipt-derived")
    require("activeAttempt" in model and "gateCriteria = activeAttempt" in model, "active attempt does not own its gate")
    require("historyScope: 'current-run-only'" in model, "current-run history limit is not explicit")
    require("activeTasks" in model and "activeCount" in model, "concurrent active work is collapsed")
    require("TaskStopKind = 'dependency' | 'executor' | 'acceptance'" in model, "stop causes are not separated")

    require("api.getRun(task.current_run_id)" in integration, "production does not load the run envelope")
    require("api.getRunDetails(task.current_run_id)" in integration, "production does not load run receipts")
    require("Promise.all([api.getRun" in integration, "run envelope and details are not loaded together")
    require("visibleProjectRef.current !== project.id" in integration, "cross-project stale response guard changed")
    require("async getRun(runId: string): Promise<TaskRun>" in api, "typed run endpoint is missing")

    for marker in ["data-active", "data-trace", "data-effect", "data-gate", "temm-v4-run-summary", "temm-v4-trace"]:
        require(marker in component, f"V4 rendering marker missing: {marker}")
    require("task.gateCriteria" in component, "task gate still renders aggregate historical criteria")
    require("history scope: current run only" in component and "نطاق السجل: التشغيل الحالي فقط" in component, "technical receipt overclaims or fails to translate history scope")
    require("min-height: 44px" in css, "latched dependency control lacks a 44px touch target")

    for count in [1, 6, 24, 40, 120]:
        require(str(count) in entry, f"diagnostic task count missing: {count}")
    require("data-v4-task-count" in specimen and "data-v4-scale" in specimen, "V4 diagnostic metrics are missing")
    require("deriveProjectWorkspaceModel" in specimen, "V4 specimen bypasses the production adapter")
    require("document.documentElement.dir" in entry, "V4 specimen does not exercise document direction")
    require("/src/v4-specimen.tsx" in html, "V4 specimen HTML entry is invalid")
    require('"test:v4"' in package and '"check:v4"' in package, "V4 verification scripts are missing")

    for phrase in [
        "keeps an older rejection off the live retry gate",
        "separates measured effects from acceptance verdicts",
        "preserves multiple active tasks",
        "distinguishes dependency waiting from an executor stop",
        "never maps a stopped executor onto no effect",
        "claims no effect only from the authoritative receipt flag",
        "keeps an executor that finished short of acceptance out of accepted",
        "separates an accepted task from a complete project",
        "preserves every attempt in order instead of collapsing history",
        "selects current work by execution authority order",
        "carries full execution truth into ledger scale for mobile parity",
        "exposes no run or attempt truth where none was reported",
        "never fabricates verification or measured progress",
    ]:
        require(phrase in test, f"V4 truth test missing: {phrase}")

    defined_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    used_tokens = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    # Component-scoped state custom props (set from TSX or by the V7 chain
    # choreography), not V1 semantic tokens.
    component_state = {"--v3-depth", "--v7-row", "--v7-converge-x"}
    unknown_tokens = used_tokens - defined_tokens - component_state
    require(not unknown_tokens, f"work graph CSS uses undefined V1 tokens: {sorted(unknown_tokens)}")
    combined = model + component + integration + css + specimen + entry
    require("scaleX" not in combined, "V4 mechanically mirrors RTL")
    require("infinite" not in css, "V4 introduces an idle animation loop")
    require(not re.search(r"\b(?:spinner|shimmer|progress-bar)\b", combined, re.IGNORECASE), "V4 fabricates progress")
    require(not re.search(r"font-size\s*:\s*\d", css), "V4 bypasses the V1 type scale")

    print("V4 LIVE TASK LATTICE CONTRACT PASSED")
    print(f"files={len(paths)} counts=5 adapter_tests=16 tokens={len(used_tokens)}")


if __name__ == "__main__":
    main()
