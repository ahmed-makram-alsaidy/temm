"""Capture and measure the V4 work graph scale/direction matrix."""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v4"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
COUNTS = [1, 6, 24, 40, 120]
VIEWPORTS = [(1600, 1000), (1440, 900), (768, 1024), (375, 812)]
SHOTS = [
    (f"v4-{count}-{width}-{'ar' if rtl else 'en'}", width, height, count, rtl, False)
    for count in COUNTS
    for width, height in VIEWPORTS
    for rtl in [False, True]
] + [
    ("v4-24-1440-en-grey", 1440, 900, 24, False, True),
    ("v4-120-375-ar-grey", 375, 812, 120, True, True),
]


async def capture(chrome: Path, base_url: str, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v4-"))
    debug_port = free_port()
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
            for name, width, height, count, rtl, grey in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 600,
                })
                query = f"count={count}&theme=dark&rtl={str(rtl).lower()}&grey={str(grey).lower()}"
                await cdp.call("Page.navigate", {"url": f"{base_url}?{query}"})
                await asyncio.sleep(.8)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True,
                    "returnByValue": True,
                })
                await asyncio.sleep(.2)
                metrics_expression = """(() => {
                  const root = document.documentElement;
                  const body = document.body;
                  const visible = (element) => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                  };
                  const offenders = [...document.querySelectorAll('body *')].filter((element) => {
                    if (!visible(element) || getComputedStyle(element).position === 'fixed') return false;
                    const rect = element.getBoundingClientRect();
                    let parent = element.parentElement;
                    while (parent) {
                      const overflow = getComputedStyle(parent).overflowX;
                      if (['auto', 'scroll', 'hidden', 'clip'].includes(overflow)) return false;
                      parent = parent.parentElement;
                    }
                    return rect.right > innerWidth + 1 || rect.left < -1;
                  }).slice(0, 12).map((element) => {
                    const rect = element.getBoundingClientRect();
                    return { tag: element.tagName, className: String(element.className).slice(0, 120), left: Math.round(rect.left), right: Math.round(rect.right) };
                  });
                  const textSizes = [...document.querySelectorAll('body *')]
                    .filter((element) => visible(element) && [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
                    .map((element) => parseFloat(getComputedStyle(element).fontSize))
                    .filter(Number.isFinite);
                  const traces = [...document.querySelectorAll('.temm-v4-trace')].filter(visible);
                  const stateText = [...document.querySelectorAll('.temm-v3-task-heading > span, .temm-v3-grouped-work > section p')].filter(visible);
                  return {
                    viewportWidth: innerWidth,
                    viewportHeight: innerHeight,
                    scrollWidth: Math.max(root.scrollWidth, body.scrollWidth),
                    workspaceVisible: Boolean(document.querySelector('.temm-v3-workspace')),
                    taskCount: Number(document.querySelector('[data-v4-task-count]')?.getAttribute('data-v4-task-count')),
                    scale: document.querySelector('[data-v4-scale]')?.getAttribute('data-v4-scale'),
                    activeCount: Number(document.querySelector('[data-v4-active-count]')?.getAttribute('data-v4-active-count')),
                    activeMarkers: document.querySelectorAll('[data-v3-task-review][data-active="true"]').length,
                    stateTextCount: stateText.length,
                    traceTargets: traces.length,
                    minimumTraceHeight: traces.length ? Math.min(...traces.map((element) => element.getBoundingClientRect().height)) : null,
                    minimumFontSize: textSizes.length ? Math.min(...textSizes) : null,
                    primaryActions: document.querySelectorAll('[data-v3-primary="true"]').length,
                    closedCells: document.querySelectorAll('.temm-closed-cell[data-state="closed"]').length,
                    documentDirection: root.dir,
                    offenders,
                  };
                })()"""
                evaluated = await cdp.call("Runtime.evaluate", {"expression": metrics_expression, "returnByValue": True})
                metrics = evaluated["result"]["value"]
                screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                screenshot_path = output / f"{name}.png"
                screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
                results.append({
                    "name": name,
                    "count": count,
                    "rtl": rtl,
                    "greyscale": grey,
                    "width": width,
                    "height": height,
                    "screenshot": screenshot_path.name,
                    **metrics,
                })
                print(f"ok   {name:26s} {screenshot_path.stat().st_size / 1024:8.1f} KB")
            return results
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
        shutil.rmtree(profile, ignore_errors=True)


def expected_scale(count: int) -> str:
    if count <= 24:
        return "lattice"
    if count <= 80:
        return "grouped"
    return "ledger"


def failed_shots(results: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for item in results:
        reasons: list[str] = []
        count = int(item["count"])
        if not item["workspaceVisible"]:
            reasons.append("workspace missing")
        if int(item["taskCount"]) != count:
            reasons.append("task count mismatch")
        if item["scale"] != expected_scale(count):
            reasons.append("scale mismatch")
        if int(item["scrollWidth"]) > int(item["viewportWidth"]):
            reasons.append("horizontal overflow")
        if item["offenders"]:
            reasons.append("visible overflow offender")
        if int(item["activeCount"]) < 1 or int(item["activeMarkers"]) < 1:
            reasons.append("active work collapsed")
        if int(item["stateTextCount"]) < 1:
            reasons.append("state lacks text")
        if item["minimumFontSize"] is None or float(item["minimumFontSize"]) < 12:
            reasons.append("type below 12px")
        if count > 1 and (int(item["traceTargets"]) < 1 or float(item["minimumTraceHeight"] or 0) < 44):
            reasons.append("dependency trace touch target below 44px")
        if int(item["primaryActions"]) > 1:
            reasons.append("multiple primary actions")
        if int(item["closedCells"]) > 0:
            reasons.append("unverified state claims Closed Cell")
        expected_direction = "rtl" if item["rtl"] else "ltr"
        if item["documentDirection"] != expected_direction:
            reasons.append("document direction mismatch")
        if reasons:
            failures.append(f"{item['name']}: {', '.join(reasons)}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.chrome.is_file():
        raise FileNotFoundError(f"Chrome not found: {args.chrome}")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}/specimen/v4.html"
    vite = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_server(base_url, vite)
        results = asyncio.run(capture(args.chrome, base_url, args.output))
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
