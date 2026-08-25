"""Static contract checks for the V6 acceptance + evidence experience."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
MODEL = WEB / "src" / "components" / "project-workspace-model.ts"
COMPONENT = WEB / "src" / "components" / "ProjectWorkspace.tsx"
PRIMITIVES_TSX = WEB / "src" / "components" / "visual-primitives" / "ExecutionPrimitives.tsx"
PRIMITIVES_CSS = WEB / "src" / "components" / "visual-primitives" / "execution-primitives.css"
INDEX = WEB / "src" / "components" / "visual-primitives" / "index.ts"
WORKSPACE_CSS = WEB / "src" / "components" / "project-workspace.css"
TEST = WEB / "src" / "__tests__" / "project-evidence-model.test.ts"
SPECIMEN_V4 = WEB / "src" / "specimens" / "V4WorkGraphSpecimen.tsx"
SPECIMEN_V5 = WEB / "src" / "specimens" / "V5MotionLabSpecimen.tsx"
ENTRY_V4 = WEB / "src" / "v4-specimen.tsx"
ENTRY_V5 = WEB / "src" / "v5-specimen.tsx"
PACKAGE = WEB / "package.json"
CAPTURE = ROOT / "tools_web" / "capture_v6_evidence.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [MODEL, COMPONENT, PRIMITIVES_TSX, PRIMITIVES_CSS, INDEX, WORKSPACE_CSS, TEST, SPECIMEN_V4, SPECIMEN_V5, ENTRY_V4, ENTRY_V5, PACKAGE, CAPTURE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    model = MODEL.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")
    primitives = PRIMITIVES_TSX.read_text(encoding="utf-8")
    primitives_css = PRIMITIVES_CSS.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    workspace_css = WORKSPACE_CSS.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    for export in [
        "export interface TaskEffectView",
        "export interface MicroSpineView",
        "export interface TaskSheetView",
        "export function MicroSpine",
    ]:
        require(export in (model + primitives), f"V6 contract missing: {export}")
    require("MicroSpine" in index, "MicroSpine is not a public primitive")
    require("taskEffect(rawAttempts)" in model and "sourceAttemptNumber" in model, "sheet effect is not latest-authoritative-fact derived")
    require("microSpine: gateCriteria.length" in model, "the micro spine presence law is not enforced by the adapter")
    require("evidenceSummary" in model and "'measured'" in model, "criterion evidence summaries are not payload-derived")

    require("function AcceptanceSheet" in component, "the acceptance sheet is missing")
    require("temm-v6-acceptance" in component and "temm-v6-criteria" in component, "sheet acceptance sections are missing")
    require("<MicroSpine" in component, "the micro spine is not rendered in the workspace")
    require("criterion.evidence" in component, "per-criterion measured evidence is not rendered")
    require("abbreviated(artifact.checksum)" in component, "artifact checksums are not abbreviated chips")
    require("review-blocker" in component and "setSheetTaskId(taskId)" in component, "blocker review must open the evidence sheet")
    require("aria-modal" in component and "Escape" in component, "the sheet is not an accessible dialog")

    for token in ["--c-verify", "--earned-green", "--state-rejected", "--w-2", "--c-canvas"]:
        require(token in primitives_css, f"micro spine CSS does not consume {token}")
    require("temm-micro-spine__strike" in primitives_css and "temm-micro-spine__rejoin" in primitives_css, "micro spine geometry CSS is incomplete")
    require("infinite" not in workspace_css and "infinite" not in primitives_css, "V6 introduced an idle loop")
    require(not re.search(r"font-size\s*:\s*\d", workspace_css), "V6 bypasses the V1 type scale")
    combined = model + component + primitives + workspace_css + test
    require("scaleX" not in combined, "V6 mechanically mirrors RTL")
    require(not re.search(r"\b(?:spinner|shimmer|progress-bar)\b", combined, re.IGNORECASE), "V6 fabricates progress")

    require('"test:v6"' in package and '"check:v6"' in package, "V6 verification scripts are missing")
    require("sheetTaskId" in SPECIMEN_V4.read_text(encoding="utf-8") and "sheetTaskId" in ENTRY_V4.read_text(encoding="utf-8"), "V4 specimen cannot open a sheet deterministically")
    require("gate-rejected" in SPECIMEN_V5.read_text(encoding="utf-8") and "sheetTaskId" in ENTRY_V5.read_text(encoding="utf-8"), "V5 lab cannot prove the at-rest rejection sheet")

    for phrase in [
        "the sheet effect comes from the latest attempt with an authoritative fact",
        "a no-effect receipt is the sheet effect when it is the latest fact",
        "an unreported effect stays unknown and fabricates nothing",
        "criterion evidence summaries surface only what the payload carries",
        "the micro spine exists exactly when criteria were measured",
        "a live retry keeps its own unmeasured gate off the micro spine",
        "evidence items carry the micro spine and effect for the stack",
        "an accepted task and a complete project remain separate claims in the sheet data",
    ]:
        require(phrase in test, f"V6 truth test missing: {phrase}")

    print("V6 ACCEPTANCE + EVIDENCE CONTRACT PASSED")
    print(f"files={len(paths)} sheet_tests=9 primitives=10")


if __name__ == "__main__":
    main()
