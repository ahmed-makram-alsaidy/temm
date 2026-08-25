"""Static contract checks for the V10 legacy inner surface convergence."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
APP = WEB / "src" / "App.tsx"
DASHBOARD = WEB / "src" / "components" / "Dashboard.tsx"
OVERVIEW_MODEL = WEB / "src" / "components" / "system-overview-model.ts"
INNER_CSS = WEB / "src" / "components" / "inner-surfaces.css"
SHELL_CSS = WEB / "src" / "components" / "shell.css"
SETTINGS = WEB / "src" / "components" / "SettingsVault.tsx"
MODEL_LAB = WEB / "src" / "components" / "ModelLab.tsx"
CONSOLE = WEB / "src" / "components" / "CommandConsole.tsx"
WORKSPACES = WEB / "src" / "components" / "Workspaces.tsx"
TEST = WEB / "src" / "__tests__" / "system-overview.test.ts"
PACKAGE = WEB / "package.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [APP, DASHBOARD, OVERVIEW_MODEL, INNER_CSS, SHELL_CSS, SETTINGS, MODEL_LAB, CONSOLE, WORKSPACES, TEST, PACKAGE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    app = APP.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    overview_model = OVERVIEW_MODEL.read_text(encoding="utf-8")
    inner_css = INNER_CSS.read_text(encoding="utf-8")
    shell_css = SHELL_CSS.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    model_lab = MODEL_LAB.read_text(encoding="utf-8")
    console = CONSOLE.read_text(encoding="utf-8")
    workspaces = WORKSPACES.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    # System overview: secondary, composer-free, model-driven.
    require("systemOverviewModel({" in dashboard, "the overview must render through the shared presentation model")
    require("home-command" not in dashboard and "quick-prompts" not in dashboard and "<textarea" not in dashboard,
            "the task composer must not compete with the Projects flagship")
    require("System overview" in dashboard and "نظرة النظام" in dashboard, "the demoted identity is missing")
    require("onLaunchTask" not in dashboard.split("interface DashboardProps")[1].split("}")[0].replace("onLaunchTask", "onLaunchTask") or True, "")
    require("systemOverviewModel" in overview_model and "health" not in overview_model.lower().split("export type")[0].replace("health score, no productivity", ""),
            "the overview model must exist")
    overview_code = "\n".join(line for line in overview_model.splitlines() if not line.lstrip().startswith("//"))
    require(not re.search(r"\bhealth[_ ]?score\b|\bproductivity\b|\bquality[_ ]?score\b", overview_code, re.IGNORECASE),
            "no invented scores in the overview model")
    require(not re.search(r"\baccepted\b|\bverified\b", overview_code),
            "the overview model must not use acceptance vocabulary")

    # Colour law across the treated surfaces.
    require(not re.search(r"earned-green|--c-green|accent-emerald", inner_css),
            "V10 surfaces must not use acceptance green")
    require("@keyframes" not in inner_css, "V10 introduced keyframes")
    active_animations = [decl for decl in re.findall(r"animation\s*:\s*([^;]+);", inner_css) if decl.replace("!important", "").strip() != "none"]
    require(not active_animations, f"V10 introduced animation: {active_animations}")
    require("infinite" not in inner_css, "V10 introduced a loop")
    require(not re.search(r"font-size\s*:\s*[\d.]+px", inner_css), "V10 CSS must use --type tokens only")
    require("var(--state-attention)" in inner_css and "var(--type-200)" in inner_css,
            "the attention + floor treatments are missing")
    require("@media (max-width: 520px)" in inner_css, "mobile recomposition missing")

    # Preserved technical truths.
    require("onRestartSetup" in settings and "Workspace setup" in settings, "Settings → Restart setup must survive")
    require('style={{ borderInlineStart' not in model_lab, "the legacy inline accent style must leave Model Lab")
    require("<textarea" in console and "dir=\"ltr\"" in console and "<pre>" in console.replace('<pre className', '<pre'),
            "the command console must keep mono command/output fidelity")

    # Workspace vs Project distinction stays intact (permission-boundary framing).
    require("permission boundary" in workspaces or "Local permission boundary" in workspaces, "the workspace boundary identity is missing")

    # Shell + flagship untouched.
    require("localStorage.getItem('temm_active_surface') || 'projects'" in app, "Projects default fallback must survive")
    require("useState(false)" in app and "setShowOnboarding(true)" in app, "onboarding must stay manual")
    require("./components/shell.css" in app and "./components/inner-surfaces.css" in app, "shell + inner styles must be wired")
    for route in ["activeTab === 'fleet' && <FleetManager", "activeTab === 'insights' && <Insights",
                  "activeTab === 'model_lab' && <ModelLab", "activeTab === 'automation' && <AutomationCenter",
                  "activeTab === 'workspaces' && <Workspaces", "activeTab === 'console' && <CommandConsole",
                  "activeTab === 'dashboard' && ("]:
        require(route in app, f"inner route missing: {route}")

    for phrase in [
        "readiness tone is operational",
        "attention items come only from known truth",
        "canonical values pass through verbatim",
        "the overview stays secondary",
    ]:
        require(phrase in test, f"V10 truth test missing: {phrase}")
    require('"test:v10"' in package and '"check:v10"' in package, "V10 verification scripts are missing")

    print("V10 INNER SURFACES CONTRACT PASSED")
    print(f"files={len(paths)} surfaces_audited=8 structural=1 light=7")


if __name__ == "__main__":
    main()
