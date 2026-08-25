"""Capture and measure the V8 supporting screens (Runs history, Run receipt narrative)."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

import websockets


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v8"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# name, width, height, surface, state, theme, rtl, greyscale
SHOTS = [
    ("v8-runs-graphite", 1440, 900, "runs", "completed", "dark", False, False),
    ("v8-runs-chalk", 1440, 900, "runs", "completed", "light", False, False),
    ("v8-details-graphite", 1440, 900, "run-details", "completed", "dark", False, False),
    ("v8-details-failed", 1440, 900, "run-details", "failed", "dark", False, False),
    ("v8-runs-rtl", 1440, 900, "runs", "completed", "dark", True, False),
    ("v8-details-rtl", 1440, 900, "run-details", "completed", "dark", True, False),
    ("v8-runs-tablet", 768, 1024, "runs", "completed", "dark", False, False),
    ("v8-details-tablet", 768, 1024, "run-details", "completed", "dark", False, False),
    ("v8-runs-mobile", 390, 844, "runs", "completed", "dark", False, False),
    ("v8-details-mobile", 390, 844, "run-details", "completed", "dark", False, False),
    ("v8-details-mobile-rtl", 390, 844, "run-details", "completed", "dark", True, False),
    ("v8-runs-greyscale", 1440, 900, "runs", "completed", "dark", False, True),
]


class Cdp:
    def __init__(self, websocket: websockets.ClientConnection) -> None:
        self.websocket = websocket
        self.sequence = 0

    async def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.sequence += 1
        request_id = self.sequence
        await self.websocket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(await self.websocket.recv())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {})


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Vite exited before the V8 specimen became available")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("Timed out waiting for the V8 specimen")


async def devtools_endpoint(port: int) -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                pages = json.load(response)
            page = next(item for item in pages if item["type"] == "page")
            return str(page["webSocketDebuggerUrl"])
        except (OSError, StopIteration):
            await asyncio.sleep(0.1)
    raise TimeoutError("Chrome DevTools endpoint did not become ready")


async def capture(chrome: Path, base_url: str, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v8-"))
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
            for name, width, height, surface, state, theme, rtl, grey in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 600,
                })
                query = f"surface={surface}&state={state}&theme={theme}&rtl={str(rtl).lower()}&grey={str(grey).lower()}"
                await cdp.call("Page.navigate", {"url": f"{base_url}?{query}"})
                await asyncio.sleep(0.9)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True,
                    "returnByValue": True,
                })
                # The L3 receipt must be open for its dedicated proof shots.
                if "details" in surface or "receipt" in name:
                    await cdp.call("Runtime.evaluate", {
                        "expression": "[...document.querySelectorAll('.temm-v8-run-receipt summary, .temm-v8-receipt-details summary')].forEach((s) => s.click())",
                        "returnByValue": True,
                    })
                    await asyncio.sleep(0.25)

                metrics_expression = """(() => {
                  const root = document.documentElement;
                  const body = document.body;
                  const offenders = [...document.querySelectorAll('body *')].filter((element) => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    if (rect.width === 0 || rect.height === 0 || style.position === 'fixed') return false;
                    let parent = element.parentElement;
                    while (parent) {
                      const parentStyle = getComputedStyle(parent);
                      if (['auto', 'scroll', 'hidden', 'clip'].includes(parentStyle.overflowX)) return false;
                      parent = parent.parentElement;
                    }
                    return rect.right > innerWidth + 1 || rect.left < -1;
                  }).slice(0, 12).map((element) => {
                    const rect = element.getBoundingClientRect();
                    return { tag: element.tagName, className: String(element.className).slice(0, 120), left: Math.round(rect.left), right: Math.round(rect.right) };
                  });
                  const smallest = Math.min(...[...document.querySelectorAll('body *')]
                    .filter((element) => [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim()))
                    .map((element) => parseFloat(getComputedStyle(element).fontSize))
                    .filter((size) => Number.isFinite(size) && size > 0));
                  return {
                    viewportWidth: innerWidth,
                    scrollWidth: Math.max(root.scrollWidth, body.scrollWidth),
                    historyRows: document.querySelectorAll('.temm-v8-run-row').length,
                    narrativeVisible: Boolean(document.querySelector('.temm-v8-narrative')),
                    chapters: document.querySelectorAll('.temm-v8-chapter').length,
                    receiptOpen: document.querySelectorAll('.temm-v8-run-receipt[open], .temm-v8-receipt-details[open]').length,
                    tables: document.querySelectorAll('table').length,
                    smallestFontPx: Number.isFinite(smallest) ? smallest : null,
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
                    "surface": surface,
                    "state": state,
                    "theme": theme,
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


def failed_shots(results: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for item in results:
        reasons: list[str] = []
        if int(item["scrollWidth"]) > int(item["viewportWidth"]):
            reasons.append("horizontal overflow")
        if item["offenders"]:
            reasons.append("visible overflow offender")
        expected_direction = "rtl" if item["rtl"] else "ltr"
        if item["documentDirection"] != expected_direction:
            reasons.append("document direction mismatch")
        if item["tables"]:
            reasons.append("a data table returned")
        if item["surface"] == "runs" and int(item["historyRows"]) == 0:
            reasons.append("history rows missing")
        if item["surface"] == "run-details":
            if not item["narrativeVisible"]:
                reasons.append("narrative missing")
            if int(item["chapters"]) < 4:
                reasons.append("causal chapters incomplete")
            if int(item["receiptOpen"]) == 0:
                reasons.append("L3 receipt did not open")
        if item["smallestFontPx"] is not None and float(item["smallestFontPx"]) < 11.5:
            reasons.append(f"font below the readable floor: {item['smallestFontPx']}")
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
    base_url = f"http://127.0.0.1:{port}/specimen/v8.html"
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
