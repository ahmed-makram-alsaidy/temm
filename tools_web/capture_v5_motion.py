"""Capture and verify the V5 motion lab frame sequence and stills."""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v5"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
STEP_MS = 900
SETTLE_MS = 700

# name, scenario, step, width, height, rtl, grey, reduced
SHOTS = [
    *(("v5-chain-%d-1440-en" % step, "retry-chain", step, 1440, 900, False, False, False) for step in range(6)),
    ("v5-chain-5-1440-ar", "retry-chain", 5, 1440, 900, True, False, False),
    ("v5-chain-2-1440-ar", "retry-chain", 2, 1440, 900, True, False, False),
    ("v5-chain-5-1440-en-grey", "retry-chain", 5, 1440, 900, False, True, False),
    ("v5-chain-5-375-en", "retry-chain", 5, 375, 812, False, False, False),
    ("v5-chain-5-1440-en-reduced", "retry-chain", 5, 1440, 900, False, False, True),
    ("v5-concurrent-1440-en", "concurrent", 1, 1440, 900, False, False, False),
    ("v5-concurrent-375-en", "concurrent", 1, 375, 812, False, False, False),
    ("v5-waiting-1440-en", "waiting", 1, 1440, 900, False, False, False),
    ("v5-blocked-1440-en", "blocked", 1, 1440, 900, False, False, False),
    ("v5-ready-running-1440-en", "ready-running", 1, 1440, 900, False, False, False),
    ("v5-no-effect-1440-en", "no-effect", 1, 1440, 900, False, False, False),
    ("v5-rejected-1440-en", "rejected", 1, 1440, 900, False, False, False),
    ("v5-accepted-1440-en", "accepted", 2, 1440, 900, False, False, False),
]


async def capture(chrome: Path, base_url: str, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v5-"))
    debug_port = free_port()
    browser = subprocess.Popen(
        [
            str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--force-color-profile=srgb",
            "--font-render-hinting=none",
            # Headless Chrome defaults to prefers-reduced-motion: reduce, which
            # would truthfully suppress every transit. The motion frames must be
            # captured under an explicit no-preference channel instead.
            "--force-prefers-reduced-motion=no-preference",
            f"--remote-debugging-port={debug_port}",
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
            for name, scenario, step, width, height, rtl, grey, reduced in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
                })
                query = (
                    f"scenario={scenario}&step={step}&play=1&rtl={str(rtl).lower()}"
                    f"&grey={str(grey).lower()}&reduced={str(reduced).lower()}"
                )
                await cdp.call("Page.navigate", {"url": f"{base_url}?{query}"})
                await asyncio.sleep(0.4)
                # Headless Chrome defaults to prefers-reduced-motion: reduce; the
                # emulation is applied once the new document has committed (it
                # does not survive navigation) so motion frames are captured
                # under no-preference. The reduced shots suppress travel through
                # TEMM's explicit data-reduce-motion channel instead.
                await cdp.call("Emulation.setEmulatedMedia", {
                    "features": [{"name": "prefers-reduced-motion", "value": "no-preference"}],
                })
                settle = (0 if reduced else step * STEP_MS) + SETTLE_MS
                await asyncio.sleep(settle / 1000 + 0.9)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True, "returnByValue": True,
                })
                await asyncio.sleep(0.2)
                metrics_expression = """(() => {
                  const visible = (element) => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    // SVG strokes have zero-area geometry boxes; a nonzero
                    // extent on either axis plus painted style is presence.
                    return style.display !== 'none' && style.visibility !== 'hidden'
                      && (rect.width > 0 || rect.height > 0);
                  };
                  const transits = [...document.querySelectorAll('.temm-connector__transit')].filter(visible);
                  const root = document.documentElement;
                  return {
                    viewportWidth: innerWidth,
                    mediaReduce: matchMedia('(prefers-reduced-motion: reduce)').matches,
                    datasetReduce: root.dataset.reduceMotion ?? 'unset',
                    transitPaths: document.querySelectorAll('.temm-connector__transit').length,
                    transitAttrs: document.querySelectorAll('[data-transit="true"]').length,
                    scrollWidth: Math.max(root.scrollWidth, document.body.scrollWidth),
                    labVisible: Boolean(document.querySelector('.temm-v5-lab')),
                    scenario: document.querySelector('[data-v5-scenario]')?.getAttribute('data-v5-scenario') ?? null,
                    step: Number(document.querySelector('[data-v5-step]')?.getAttribute('data-v5-step')),
                    transitCount: transits.length,
                    activeMarkers: document.querySelectorAll('[data-v3-task-review][data-active=\\'true\\']').length,
                    motionMarks: document.querySelectorAll('[data-motion]').length,
                    attemptRows: document.querySelectorAll('.temm-v3-attempt-list li').length,
                    arrivedRows: document.querySelectorAll('.temm-v3-attempt-list li[data-arrived=\\'true\\']').length,
                    gates: document.querySelectorAll('.temm-gate').length,
                    acceptedGates: document.querySelectorAll('.temm-gate[data-state=\\'accepted\\']').length,
                    rejectedGates: document.querySelectorAll('.temm-gate[data-state=\\'rejected\\']').length,
                    closedCells: document.querySelectorAll('.temm-closed-cell[data-state=\\'closed\\']').length,
                    minimumFontSize: (() => {
                      const sizes = [...document.querySelectorAll('body *')]
                        .filter((element) => visible(element) && [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
                        .map((element) => parseFloat(getComputedStyle(element).fontSize))
                        .filter(Number.isFinite);
                      return sizes.length ? Math.min(...sizes) : null;
                    })(),
                    documentDirection: root.dir,
                    reduceMotion: root.dataset.reduceMotion === 'true',
                  };
                })()"""
                evaluated = await cdp.call("Runtime.evaluate", {"expression": metrics_expression, "returnByValue": True})
                metrics = evaluated["result"]["value"]
                screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                screenshot_path = output / f"{name}.png"
                screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
                results.append({
                    "name": name, "scenario": scenario, "step": step, "rtl": rtl,
                    "greyscale": grey, "reduced": reduced, "width": width,
                    "screenshot": screenshot_path.name, **metrics,
                })
                print(f"ok   {name:30s} transit={metrics['transitCount']} {screenshot_path.stat().st_size / 1024:8.1f} KB")
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
        if not item["labVisible"]:
            reasons.append("motion lab missing")
        if int(item["scrollWidth"]) > int(item["viewportWidth"]) + 1:
            reasons.append("horizontal overflow")
        expected_direction = "rtl" if item["rtl"] else "ltr"
        if item["documentDirection"] != expected_direction:
            reasons.append("direction mismatch")
        minimum = item["minimumFontSize"]
        if minimum is None or float(minimum) < 12:
            reasons.append("type below 12px")
        reduced = bool(item["reduced"])
        if reduced and int(item["transitCount"]) != 0:
            reasons.append("reduced motion still travels")
        if name == "v5-concurrent-1440-en" and int(item["transitCount"]) != 3:
            reasons.append(f"concurrency cap broken: {item['transitCount']} transits")
        if name == "v5-concurrent-375-en" and int(item["transitCount"]) != 3:
            reasons.append(f"mobile concurrency cap broken: {item['transitCount']} transits")
        if name.startswith("v5-chain-") and not reduced:
            step = int(item["step"])
            # Steps 0 and 5 are settled (ready, accepted); 1-4 carry one live run.
            expected_transit = 1 if 1 <= step <= 4 else 0
            if int(item["transitCount"]) != expected_transit:
                reasons.append(f"chain step {step}: expected {expected_transit} transit, saw {item['transitCount']}")
        if name == "v5-chain-5-1440-en":
            if int(item["acceptedGates"]) < 2:
                reasons.append("chain end lacks accepted gates")
            if int(item["attemptRows"]) < 3:
                reasons.append("chain end lost attempt history")
            if int(item["closedCells"]) != 0:
                reasons.append("unverified state claims a Closed Cell")
        if name == "v5-chain-5-1440-en-reduced" and int(item["attemptRows"]) < 3:
            reasons.append("reduced chain lost attempt history")
        if name == "v5-blocked-1440-en" and int(item["transitCount"]) != 0:
            reasons.append("blocked work is travelling")
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
    base_url = f"http://127.0.0.1:{port}/specimen/v5.html"
    vite = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True,
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
