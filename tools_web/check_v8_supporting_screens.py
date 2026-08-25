"""Static contract checks for the V8 supporting project screens."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
RUNS = WEB / "src" / "components" / "Runs.tsx"
RUN_DETAILS = WEB / "src" / "components" / "RunDetails.tsx"
MODEL = WEB / "src" / "components" / "supporting-screens-model.ts"
CSS = WEB / "src" / "components" / "supporting-screens.css"
PROJECTS = WEB / "src" / "components" / "Projects.tsx"
APP = WEB / "src" / "App.tsx"
TEST = WEB / "src" / "__tests__" / "supporting-screens.test.ts"
SPECIMEN_TSX = WEB / "src" / "specimens" / "V8SupportSpecimen.tsx"
SPECIMEN_HTML = WEB / "specimen" / "v8.html"
PACKAGE = WEB / "package.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [RUNS, RUN_DETAILS, MODEL, CSS, PROJECTS, APP, TEST, SPECIMEN_TSX, SPECIMEN_HTML, PACKAGE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    runs = RUNS.read_text(encoding="utf-8")
    details = RUN_DETAILS.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    projects = PROJECTS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    # Runs: outcome-first history, not a database grid.
    require("<table" not in runs and "runs-table" not in runs, "the Runs screen still renders the 8-column database grid")
    require("temm-v8-run-row" in runs and "temm-v8-run-prompt" in runs and "temm-v8-run-sentence" in runs,
            "the outcome-first history rows are missing")
    require("status-badge" not in runs, "generic status pills must not return on the Runs screen")
    require("onOpenRun" in runs and "onNewTask" in runs and "compareRuns" in runs and 'setQuery' in runs,
            "search, compare, and open-run behaviour must survive the redesign")
    require("runOutcomeSentence(run.status" in runs and "needsAttention(run.status)" in runs,
            "outcome sentences must classify the backend's own status only")

    # RunDetails: causal narrative with L3 receipt preserved.
    require("run-evidence-grid" not in details and "surface-card\"><h3>" not in details,
            "RunDetails still opens on schema-shaped cards")
    require("What it produced" in details or "ما أنتجته" in details, "the produced-output chapter is missing")
    require("Measured facts" in details and "measuredFactRows(run, details)" in details,
            "the measured-facts projection is missing")
    require("Full technical receipt" in details and "Event log" in details,
            "the L3 technical receipt disclosure is missing")
    require("attemptLines(details)" in details and "artifactRows(details)" in details and "technicalReceiptLines(run, details)" in details,
            "RunDetails must render through the shared presentation model")
    require(not re.search(r"\b(accepted|verified)\b", details),
            "RunDetails must never claim acceptance or verification for a task run")
    require("title={artifact.fullHash" in details.replace("artifact.fullHash ?? undefined", "artifact.fullHash"),
            "the full artifact hash must stay reachable (title) beside its chip")

    # Presentation model: labels only — no second truth source.
    # Comments may state the intent; CODE must never touch project truth.
    model_code = "\n".join(line for line in model.splitlines() if not line.lstrip().startswith("//"))
    require(not re.search(r"\bcompletion\b|\bready\b|\bverified\b|\baccepted\b|\bacceptance\b", model_code),
            "the run presentation model must not compute project/acceptance truth")
    require("api." not in model_code, "the presentation model stays pure: no fetching")
    require("project-workspace-model" not in model.splitlines()[0] + "".join(l for l in model.splitlines() if l.strip().startswith("import")),
            "the run presentation model must stay decoupled from the task-truth adapter")

    # Visual system discipline.
    require(not re.search(r"font-size\s*:\s*\d", css), "V8 bypasses the V1 type scale")
    require("@keyframes" not in css and "animation" not in css and "infinite" not in css, "V8 introduced new motion")
    for token in ["var(--role-", "var(--sp-", "var(--c-rule)", "var(--c-focus)", "var(--state-attention)"]:
        require(token in css, f"V8 CSS must consume the frozen tokens ({token})")
    require("@media (max-width: 520px)" in css, "mobile recomposition is missing")

    # Earned green belongs to acceptance/verification (V5–V7 law). A completed
    # RUN is execution completion only: its dot and verdict must be neutral
    # operational ink, never the earned-green/acceptance semantic.
    completed_blocks = re.findall(r"\.temm-v8-(?:run-mark|narrative-verdict)[^\n]*\{[^}]*\}", css)
    completed_rules = " ".join(
        block for block in completed_blocks
        if "data-outcome='completed'" in block or "data-outcome=\"completed\"" in block
    )
    require(bool(completed_rules), "completed-outcome styling rules are missing")
    require(not re.search(r"earned-green|state-accepted|--c-green", completed_rules),
            "a completed run must not wear the earned-green acceptance semantic")
    require("var(--c-ink-1)" in completed_rules, "completed runs must use the neutral operational ink treatment")
    require("var(--earned-green)" not in css, "earned green has no operational use on the Runs surfaces")

    # Project/work identity is part of the L1 reading order, before any
    # technical disclosure — resolved from the existing project list.
    require("projectLabel(run.project_id, projects)" in runs, "Runs L1 must resolve owning-project context")
    require("temm-v8-run-project" in runs and "temm-v8-run-project" in css,
            "the project label is not rendered inside the L1 sentence")
    require("api.listProjects()" in runs, "project names must come from the existing projects list")
    require(runs.count("api.") <= 3, "project context must not become per-row requests")

    # Flagship preservation + real-product wiring.
    require("./ProjectWorkspace'" in projects and "<ProjectWorkspace" in projects, "Projects no longer renders the flagship workspace")
    require("activeTab === 'projects' && <Projects" in app, "the flagship route left the product navigation")
    require("activeTab === 'runs' && <Runs" in app, "the Runs route left the product navigation")
    require("<RunDetails run={run} isArabic={isArabic}" in app or "RunDetails run={run}" in app or "import { RunDetails }" in open(WEB / "src" / "components" / "RunWorkspace.tsx", encoding="utf-8").read(),
            "RunDetails no longer reachable from the product run screen")
    require(re.search(r"showOnboarding,\s*setShowOnboarding\]\s*=\s*useState\(false\)", app) is not None,
            "legacy onboarding must stay non-auto-launching")
    require("The boundary is a promise" in projects or "وعد الحد" in projects,
            "the folder-boundary promise line (§17.12) is missing from setup")

    # Verification aids exist but are dev-only.
    require('robots" content="noindex,nofollow"' in SPECIMEN_HTML.read_text(encoding="utf-8"), "the V8 specimen page must be marked dev-only")

    # Tests + scripts.
    for phrase in [
        "the understood station presents the blueprint verbatim",
        "requirements carry statements only",
        "run history labels classify status only",
        "measured facts project record values exactly",
        "artifact chips abbreviate to seven characters",
        "the technical receipt keeps every L3 field",
        "flagship derivation is untouched",
        "every backend run status maps to exactly one honest outcome kind",
    ]:
        require(phrase in test, f"V8 truth test missing: {phrase}")
    require('"test:v8"' in package and '"check:v8"' in package, "V8 verification scripts are missing")

    print("V8 SUPPORTING SCREENS CONTRACT PASSED")
    print(f"files={len(paths)} surfaces=2 chapters=5 l3_lines=preserved")


if __name__ == "__main__":
    main()
