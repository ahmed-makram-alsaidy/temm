"""Capture and verify the V7 deliverable convergence frame sequence."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import websockets

from capture_v3_workspace import Cdp, devtools_endpoint, free_port, wait_for_server


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v7"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
STEP_MS = 900
CHAIN_MS = 1400

# name, query, width, height, rtl, grey, reduced, settle_ms_after_nav
SHOTS = [
    ("v7-chain-0-stillness-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + 200),
    ("v7-chain-1-gates-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + 300),
    ("v7-chain-2-converge-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + 700),
    ("v7-chain-3-retire-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + 1050),
    ("v7-chain-4-seal-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + 1350),
    ("v7-resting-1440-en", "scenario=convergence&step=1&play=1", 1440, 900, False, False, False, STEP_MS + CHAIN_MS + 1400),
    ("v7-resting-rtl-1440-ar", "scenario=convergence&step=1&play=1&rtl=1", 1440, 900, True, False, False, STEP_MS + CHAIN_MS + 1400),
    ("v7-resting-grey-1440-en", "scenario=convergence&step=1&play=1&grey=1", 1440, 900, False, True, False, STEP_MS + CHAIN_MS + 1400),
    ("v7-resting-mobile-375-en", "scenario=convergence&step=1&play=1", 375, 812, False, False, False, STEP_MS + CHAIN_MS + 1400),
    ("v7-resting-reduced-1440-en", "scenario=convergence&step=1&play=1&reduced=1", 1440, 900, False, False, True, 2200),
    ("v7-unverified-1440-en", "scenario=convergence&step=0&play=1", 1440, 900, False, False, False, 1400),
]


async def capture(chrome: Path, base_url: str, debug_port: int, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v7-"))
    browser = subprocess.Popen(
        [
            str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--force-color-profile=srgb",
            "--font-render-hinting=none", f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        endpoint = await devtools_endpoint(debug_port)
        async with websockets.connect(endpoint, max_size=24 * 1024 * 1024) as websocket:
            cdp = Cdp(websocket)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            results: list[dict[str, object]] = []
            for name, query, width, height, rtl, grey, reduced, settle_ms in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
                })
                await cdp.call("Page.navigate", {"url": f"{base_url}?{query}"})
                await asyncio.sleep(0.4)
                await cdp.call("Emulation.setEmulatedMedia", {
                    "features": [{"name": "prefers-reduced-motion", "value": "no-preference"}],
                })
                await asyncio.sleep(max(0, settle_ms - 400) / 1000)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True, "returnByValue": True,
                })
                await asyncio.sleep(0.15)
                metrics_expression = """(() => {
                  const visible = (element) => {
                    if (typeof element.checkVisibility === 'function' && !element.checkVisibility({ visibilityProperty: true })) return false;
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0;
                  };
                  const root = document.documentElement;
                  const seal = [...document.querySelectorAll('.temm-v7-seal .temm-closed-cell')].filter(visible)[0];
                  const sealLower = seal?.querySelector('.temm-cell__lower');
                  const sealGate = seal?.querySelector('.temm-cell__gate');
                  const sealClosed = Boolean(seal?.querySelector('.temm-cell__lower'));
                  const textSizes = [...document.querySelectorAll('body *')]
                    .filter((element) => visible(element) && [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
                    .map((element) => parseFloat(getComputedStyle(element).fontSize))
                    .filter(Number.isFinite);
                  return {
                    viewportWidth: innerWidth,
                    scrollWidth: Math.max(root.scrollWidth, document.body.scrollWidth),
                    converging: document.querySelector('[data-convergence=\\'true\\']') !== null,
                    transientLattice: [...document.querySelectorAll('[data-converging=\\'true\\'] .temm-v3-lattice-task')].filter(visible).length,
                    retiredRecord: [...document.querySelectorAll('.temm-v3-retired-work')].filter(visible).length,
                    sealPresent: Boolean(seal),
                    sealSize: seal ? Math.round(seal.getBoundingClientRect().width) : null,
                    sealDrawn: sealClosed ? (sealLower ? getComputedStyle(sealLower).strokeDashoffset !== '20' : true) && (sealGate ? getComputedStyle(sealGate).strokeDashoffset !== '14' : true) : false,
                    sealAnimating: sealLower ? getComputedStyle(sealLower).animationName !== 'none' : false,
                    restingCopy: [...document.querySelectorAll('.temm-v7-name, .temm-v7-receipt')].filter(visible).length,
                    packageMark: [...document.querySelectorAll('.temm-v7-seal .temm-evidence-package')].filter(visible).length,
                    whatVerified: [...document.querySelectorAll('.temm-v7-what-verified')].filter(visible).length,
                    downloadAction: [...document.querySelectorAll('.temm-v3-delivery [data-v3-primary=\\'true\\']')].filter(visible).length,
                    microSpines: [...document.querySelectorAll('.temm-micro-spine')].filter(visible).length,
                    minimumFontSize: textSizes.length ? Math.min(...textSizes) : null,
                    documentDirection: root.dir,
                  };
                })()"""
                evaluated = await cdp.call("Runtime.evaluate", {"expression": metrics_expression, "returnByValue": True})
                metrics = evaluated["result"]["value"]
                screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                screenshot_path = output / f"{name}.png"
                screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
                results.append({
                    "name": name, "query": query, "width": width, "rtl": rtl,
                    "greyscale": grey, "reduced": reduced, "settle_ms": settle_ms,
                    "screenshot": screenshot_path.name, **metrics,
                })
                print(f"ok   {name:32s} chain={metrics['converging']} seal={metrics['sealPresent']}/{metrics['sealSize']} {screenshot_path.stat().st_size / 1024:8.1f} KB")
            return results
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
        shutil.rmtree(profile, ignore_errors=True)


def failed_shots(results: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for item in results:
        reasons: list[str] = []
        name = str(item["name"])
        if int(item["scrollWidth"]) > int(item["viewportWidth"]) + 1:
            reasons.append("horizontal overflow")
        expected_direction = "rtl" if item["rtl"] else "ltr"
        if item["documentDirection"] != expected_direction:
            reasons.append("direction mismatch")
        minimum = item["minimumFontSize"]
        if minimum is None or float(minimum) < 12:
            reasons.append("type below 12px")
        reduced = bool(item["reduced"])
        if name.startswith("v7-chain-"):
            if not item["converging"]:
                reasons.append("the chain is not playing")
            if reduced:
                reasons.append("reduced motion played the chain")
            if int(item["transientLattice"]) < 1:
                reasons.append("the transient lattice is missing")
        if name in ("v7-chain-1-gates-1440-en", "v7-chain-2-converge-1440-en", "v7-chain-3-retire-1440-en"):
            if int(item["microSpines"]) != 0:
                reasons.append("a spine appeared outside its containment during the chain")
        if name == "v7-chain-4-seal-1440-en" and not item["sealAnimating"]:
            reasons.append("the seal is not closing at step 5")
        if name == "v7-resting-1440-en":
            if item["converging"]:
                reasons.append("the chain never handed over to the resting composition")
            if not item["sealPresent"] or not item["sealDrawn"]:
                reasons.append("the resting seal is not closed")
            if int(item["sealSize"] or 0) < 96:
                reasons.append(f"the seal is below deliverable scale: {item['sealSize']}")
            if int(item["restingCopy"]) < 2 or int(item["whatVerified"]) < 1 or int(item["downloadAction"]) < 1:
                reasons.append("the resting composition is incomplete")
            if int(item["packageMark"]) < 1:
                reasons.append("the package verification mark is missing")
            if int(item["retiredRecord"]) < 1:
                reasons.append("the lattice did not retire into its record")
        if name == "v7-resting-reduced-1440-en":
            if item["converging"]:
                reasons.append("reduced motion entered the chain state")
            if not item["sealPresent"] or not item["sealDrawn"]:
                reasons.append("reduced motion did not render the final seal")
        if name == "v7-unverified-1440-en":
            if item["converging"] or item["sealPresent"]:
                reasons.append("an unverified project shows the seal or the chain")
        if reasons:
            failures.append(f"{name}: {', '.join(reasons)}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.chrome.is_file():
        raise FileNotFoundError(f"Chrome not found: {args.chrome}")

    port = free_port()
    debug_port = free_port()
    while debug_port == port:
        debug_port = free_port()
    base_url = f"http://127.0.0.1:{port}/specimen/v5.html"
    vite = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True,
    )
    try:
        wait_for_server(base_url, vite)
        results = asyncio.run(capture(args.chrome, base_url, debug_port, args.output))
    finally:
        vite.terminate()
        try:
            vite.wait(timeout=10)
        except subprocess.TimeoutExpired:
            vite.kill()

    report = args.output / "report.json"
    failures = failed_shots(results)
    report.write_text(json.dumps({"shots": results, "failures": failures}, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(results), "failed": len(failures), "report": str(report)}, indent=2))
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
