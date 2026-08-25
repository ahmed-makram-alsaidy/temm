"""Capture and verify the V6 acceptance + evidence experience."""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v6"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# name, base(v4|v5), query, width, height, rtl, grey
SHOTS = [
    ("v6-sheet-accepted-1440-en", "v4", "count=6&sheet=1", 1440, 900, False, False),
    ("v6-sheet-recovery-1440-en", "v4", "count=6&sheet=2", 1440, 900, False, False),
    ("v6-sheet-rejected-1440-en", "v5", "scenario=gate-rejected&step=1&play=1&sheet=1", 1440, 900, False, False),
    ("v6-sheet-rtl-1440-ar", "v4", "count=6&sheet=1&rtl=1", 1440, 900, True, False),
    ("v6-sheet-grey-1440-en", "v4", "count=6&sheet=1&grey=1", 1440, 900, False, True),
    ("v6-sheet-mobile-375-en", "v4", "count=6&sheet=1", 375, 812, False, False),
    ("v6-evidence-stack-1440-en", "v4", "count=6&evidence=1", 1440, 900, False, False),
    ("v6-lattice-1440-en", "v4", "count=6", 1440, 900, False, False),
]


async def capture(chrome: Path, base_urls: dict[str, str], debug_port: int, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v6-"))
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
            for name, base, query, width, height, rtl, grey in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600,
                })
                await cdp.call("Page.navigate", {"url": f"{base_urls[base]}?{query}"})
                await asyncio.sleep(1.8)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True, "returnByValue": True,
                })
                # The evidence stack is collapsed by default; open it for the stack shot.
                if "evidence=1" in query:
                    await cdp.call("Runtime.evaluate", {"expression": """
                      const details = document.querySelector('.temm-v3-station.temm-v3-evidence');
                      if (details instanceof HTMLDetailsElement) details.open = true;
                      true
                    """, "returnByValue": True})
                    await asyncio.sleep(0.4)
                metrics_expression = """(() => {
                  const sheet = document.querySelector('.temm-v6-acceptance');
                  const visible = (element) => {
                    // checkVisibility() respects closed <details> content
                    // (content-visibility), which keeps layout geometry even
                    // though nothing is painted.
                    if (typeof element.checkVisibility === 'function' && !element.checkVisibility({ visibilityProperty: true })) return false;
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0;
                  };
                  const root = document.documentElement;
                  const textSizes = [...document.querySelectorAll('body *')]
                    .filter((element) => visible(element) && [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
                    .map((element) => parseFloat(getComputedStyle(element).fontSize))
                    .filter(Number.isFinite);
                  return {
                    viewportWidth: innerWidth,
                    scrollWidth: Math.max(root.scrollWidth, document.body.scrollWidth),
                    sheetOpen: Boolean(sheet && visible(sheet)),
                    sheetState: sheet?.getAttribute('data-state') ?? null,
                    microSpines: [...document.querySelectorAll('.temm-micro-spine')].filter(visible).length,
                    fullGates: [...document.querySelectorAll('.temm-v6-gate-full')].filter(visible).length,
                    criteriaRows: [...document.querySelectorAll('.temm-v6-criteria li')].length,
                    evidenceChips: [...document.querySelectorAll('.temm-v6-effect-paths code, .temm-v6-artifacts code')].filter(visible).length,
                    checksumChips: [...document.querySelectorAll('.temm-v6-artifacts .temm-v3-checksum')].filter(visible).length,
                    attemptRows: [...document.querySelectorAll('.temm-v6-acceptance .temm-v3-attempt-list li')].length,
                    technicalReceipts: [...document.querySelectorAll('.temm-v6-acceptance .temm-v3-technical-receipt')].length,
                    evidenceStackItems: [...document.querySelectorAll('.temm-v3-evidence-body article')].filter(visible).length,
                    triggers: [...document.querySelectorAll('.temm-v6-acceptance-trigger')].filter(visible).length,
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
                    "name": name, "base": base, "query": query, "width": width,
                    "rtl": rtl, "greyscale": grey, "screenshot": screenshot_path.name, **metrics,
                })
                print(f"ok   {name:30s} sheet={metrics['sheetOpen']} spines={metrics['microSpines']} {screenshot_path.stat().st_size / 1024:8.1f} KB")
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
        wants_sheet = "sheet=" in str(item["query"])
        if wants_sheet and not item["sheetOpen"]:
            reasons.append("acceptance sheet did not open")
        if not wants_sheet and item["sheetOpen"]:
            reasons.append("sheet opened without being asked")
        if name == "v6-sheet-accepted-1440-en":
            if int(item["microSpines"]) < 1:
                reasons.append("accepted sheet lacks the micro spine")
            if int(item["criteriaRows"]) < 1:
                reasons.append("accepted sheet lacks criterion rows")
            if int(item["attemptRows"]) < 1:
                reasons.append("accepted sheet lacks attempt history")
            if int(item["technicalReceipts"]) != 1:
                reasons.append("accepted sheet lacks the L3 receipt")
        if name == "v6-sheet-recovery-1440-en":
            if int(item["attemptRows"]) < 3:
                reasons.append(f"recovery history incomplete: {item['attemptRows']} rungs")
            if int(item["microSpines"]) != 0:
                reasons.append("a live retry claims a verdict")
        if name == "v6-sheet-rejected-1440-en":
            if int(item["microSpines"]) < 1:
                reasons.append("rejected sheet lacks the micro spine")
            if int(item["checksumChips"]) < 1:
                reasons.append("rejected sheet lacks the artifact checksum")
        if name == "v6-evidence-stack-1440-en":
            if int(item["evidenceStackItems"]) < 1:
                reasons.append("evidence stack did not open")
            if int(item["microSpines"]) < 1:
                reasons.append("evidence stack lacks micro spines")
        if name == "v6-lattice-1440-en" and int(item["triggers"]) < 1:
            reasons.append("lattice lacks acceptance sheet triggers")
        if reasons:
            failures.append(f"{name}: {', '.join(reasons)}")
    return failures


def unique_ports(count: int) -> list[int]:
    # free_port() binds, reads and releases; on Windows two quick calls can
    # return the same ephemeral port, which --strictPort then kills. Allocate
    # distinct ports up front.
    ports: list[int] = []
    while len(ports) < count:
        candidate = free_port()
        if candidate not in ports:
            ports.append(candidate)
    return ports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.chrome.is_file():
        raise FileNotFoundError(f"Chrome not found: {args.chrome}")

    port_v4, port_v5, debug_port = unique_ports(3)
    base_urls = {
        "v4": f"http://127.0.0.1:{port_v4}/specimen/v4.html",
        "v5": f"http://127.0.0.1:{port_v5}/specimen/v5.html",
    }
    vites = []
    try:
        # Start the two specimen servers sequentially: parallel vite startups
        # raced each other on Windows and the first process exited.
        for base_key, port in (("v4", port_v4), ("v5", port_v5)):
            vite = subprocess.Popen(["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
                                    cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True)
            vites.append(vite)
            wait_for_server(base_urls[base_key], vite)
        results = asyncio.run(capture(args.chrome, base_urls, debug_port, args.output))
    finally:
        for vite in vites:
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
