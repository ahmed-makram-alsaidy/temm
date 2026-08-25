"""Static contract checks for the V11 final product acceptance."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
APP = WEB / "src" / "App.tsx"
THEME_CSS = WEB / "src" / "styles" / "theme.css"
PACKAGE = WEB / "package.json"

def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

def main() -> None:
    paths = [APP, THEME_CSS, PACKAGE]
    for path in paths:
        require(path.is_file(), f"missing file: {path.relative_to(ROOT)}")

    app = APP.read_text(encoding="utf-8")
    theme_css = THEME_CSS.read_text(encoding="utf-8")
    package = PACKAGE.read_text(encoding="utf-8")

    # Projects default preserved
    require("localStorage.getItem('temm_active_surface') || 'projects'" in app,
            "Projects must remain the default fallback surface")
    # onboarding manual-only
    require("useState(false)" in app and "setShowOnboarding(true)" in app,
            "onboarding stays manual (Settings → Restart setup)")
            
    # earned green semantic restrictions in theme.css
    require(not re.search(r"--accent-emerald:\s*#(?!.*var)", theme_css), "theme.css must not define hardcoded emerald")
    require(not re.search(r"font-size:\s*([0-9]|10|11)(\.[0-9]+)?px;", theme_css), "theme.css must not use <12px text")
    require(not re.search(r"animation:\s*pulse[^;]+infinite;", theme_css), "theme.css must not have pulse loops")

    print("V11 FINAL ACCEPTANCE CONTRACT PASSED")

if __name__ == "__main__":
    main()
