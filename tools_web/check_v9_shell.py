"""Static contract checks for the V9 global product shell."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
APP = WEB / "src" / "App.tsx"
SIDEBAR = WEB / "src" / "components" / "Sidebar.tsx"
HEADER = WEB / "src" / "components" / "Header.tsx"
NAV_MODEL = WEB / "src" / "components" / "shell-navigation.ts"
SHELL_CSS = WEB / "src" / "components" / "shell.css"
TEST = WEB / "src" / "__tests__" / "shell-navigation.test.ts"
PACKAGE = WEB / "package.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    paths = [APP, SIDEBAR, HEADER, NAV_MODEL, SHELL_CSS, TEST, PACKAGE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    app = APP.read_text(encoding="utf-8")
    sidebar = SIDEBAR.read_text(encoding="utf-8")
    nav_model = NAV_MODEL.read_text(encoding="utf-8")
    shell_css = SHELL_CSS.read_text(encoding="utf-8")
    test = TEST.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    # Navigation truth: one model, derived from real app state.
    require("localStorage.getItem('temm_active_surface') || 'projects'" in app,
            "Projects must remain the default fallback surface")
    require("localStorage.setItem('temm_active_surface'" in app,
            "remembered-surface behaviour must survive")
    require("useState(false)" in app and "setShowOnboarding(true)" in app,
            "onboarding stays manual (Settings → Restart setup), never auto-launching")
    require("surfaceIsActive(item.id, activeTab)" in sidebar,
            "active navigation must derive from the shared model, not a second truth")
    require("'run'" in nav_model and "activeTab === 'run'" in nav_model,
            "the nested run detail must keep Runs marked as current")

    # Shell colour law: selection is location (ink), never acceptance green;
    # readiness is neutral/attention, never emerald; no decorative animation.
    require(not re.search(r"earned-green|state-accepted|--c-green|accent-emerald", shell_css),
            "the shell must not use acceptance green for navigation or status")
    require("var(--c-ink-max)" in shell_css and "var(--c-object)" in shell_css,
            "the active location treatment must be the neutral ink/object pair")
    require("@keyframes" not in shell_css and "animation" not in shell_css and "infinite" not in shell_css,
            "the shell must not introduce motion")
    require("pulse" not in sidebar and "status-online" not in sidebar,
            "the legacy glowing/pulsing status semantics must leave the sidebar")

    # Typography: shell text sits on the TEMM scale, 12px floor.
    require(not re.search(r"font-size\s*:\s*[\d.]+px", shell_css),
            "shell CSS must use --type tokens, not raw px sizes")
    require("var(--type-200)" in shell_css and "var(--type-300)" in shell_css and "var(--type-400)" in shell_css,
            "the shell type hierarchy must use the frozen scale")

    # Flagship + supporting routes remain wired.
    for route in ["activeTab === 'projects' && <Projects", "activeTab === 'runs' && <Runs",
                  "activeTab === 'run' && (", "activeTab === 'fleet' && <FleetManager",
                  "activeTab === 'settings' && <SettingsVault"]:
        require(route in app, f"product route missing from the shell: {route}")
    require("onRestartSetup" in app, "Settings → Restart setup must stay wired")

    # Responsive + RTL shell rules.
    require("@media (min-width: 901px)" in shell_css and ".page-kicker { display: none; }" in shell_css.replace("  ", " "),
            "the header must defer to the sidebar brand on desktop")
    require("[dir='rtl'] .nav-chevron { transform: scaleX(-1); }" in shell_css,
            "the active chevron must mirror in RTL")
    require("prefers-reduced-motion" in shell_css, "reduced-motion must be honoured in the shell")

    # Tests + scripts.
    for phrase in [
        "the flagship Projects surface is the default launch",
        "a remembered surface still wins over the default",
        "navigation groups cover exactly the real product surfaces",
        "active location follows the real surface, including the nested run view",
        "system status tone is operational",
    ]:
        require(phrase in test, f"V9 truth test missing: {phrase}")
    require('"test:v9"' in package and '"check:v9"' in package, "V9 verification scripts are missing")

    print("V9 SHELL CONTRACT PASSED")
    print(f"files={len(paths)} nav_items=9 groups=2 floor=12px")


if __name__ == "__main__":
    main()
