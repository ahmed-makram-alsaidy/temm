"""Capture and measure the V3 Project Workspace specimen through Vite."""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v3"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# name, width, height, state, theme, rtl, greyscale
SHOTS = [
    ("v3-graphite-ready", 1440, 900, "ready", "dark", False, False),
    ("v3-graphite-live", 1440, 900, "live", "dark", False, False),
    ("v3-graphite-attention", 1440, 900, "attention", "dark", False, False),
    ("v3-graphite-verified", 1440, 900, "verified", "dark", False, False),
    ("v3-chalk-ready", 1440, 900, "ready", "light", False, False),
    ("v3-chalk-live", 1440, 900, "live", "light", False, False),
    ("v3-chalk-attention", 1440, 900, "attention", "light", False, False),
    ("v3-chalk-verified", 1440, 900, "verified", "light", False, False),
    ("v3-rtl-live", 1440, 900, "live", "dark", True, False),
    ("v3-rtl-verified", 1440, 900, "verified", "dark", True, False),
    ("v3-tablet-ready", 768, 1024, "ready", "dark", False, False),
    ("v3-tablet-live", 768, 1024, "live", "dark", False, False),
    ("v3-tablet-attention", 768, 1024, "attention", "dark", False, False),
    ("v3-tablet-verified", 768, 1024, "verified", "dark", False, False),
    ("v3-mobile-live", 390, 844, "live", "dark", False, False),
    ("v3-mobile-attention", 390, 844, "attention", "dark", False, False),
    ("v3-mobile-verified", 390, 844, "verified", "dark", False, False),
    ("v3-greyscale-live", 1440, 900, "live", "dark", False, True),
    ("v3-greyscale-attention", 1440, 900, "attention", "dark", False, True),
    ("v3-greyscale-verified", 1440, 900, "verified", "dark", False, True),
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
            raise RuntimeError("Vite exited before the V3 specimen became available")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("Timed out waiting for the V3 specimen")


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
    profile = Path(tempfile.mkdtemp(prefix="temm-v3-"))
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
            for name, width, height, state, theme, rtl, grey in SHOTS:
                await cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 600,
                })
                query = f"state={state}&theme={theme}&rtl={str(rtl).lower()}&grey={str(grey).lower()}"
                await cdp.call("Page.navigate", {"url": f"{base_url}?{query}"})
                await asyncio.sleep(0.8)
                await cdp.call("Runtime.evaluate", {
                    "expression": "document.fonts.ready.then(() => true)",
                    "awaitPromise": True,
                    "returnByValue": True,
                })
                await asyncio.sleep(0.2)

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
                  return {
                    viewportWidth: innerWidth,
                    viewportHeight: innerHeight,
                    scrollWidth: Math.max(root.scrollWidth, body.scrollWidth),
                    workspaceVisible: Boolean(document.querySelector('.temm-v3-workspace')),
                    primaryActions: document.querySelectorAll('[data-v3-primary="true"]').length,
                    closedCells: document.querySelectorAll('.temm-closed-cell[data-state="closed"]').length,
                    documentDirection: root.dir,
                    specimenState: document.querySelector('[data-specimen-state]')?.getAttribute('data-specimen-state'),
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
        if not item["workspaceVisible"]:
            reasons.append("workspace missing")
        if int(item["scrollWidth"]) > int(item["viewportWidth"]):
            reasons.append("horizontal overflow")
        if item["offenders"]:
            reasons.append("visible overflow offender")
        if int(item["primaryActions"]) > 1:
            reasons.append("multiple primary actions")
        expected_direction = "rtl" if item["rtl"] else "ltr"
        if item["documentDirection"] != expected_direction:
            reasons.append("document direction mismatch")
        if item["state"] == "verified" and int(item["closedCells"]) == 0:
            reasons.append("verified state lacks Closed Cell")
        if item["state"] != "verified" and int(item["closedCells"]) > 0:
            reasons.append("unverified state claims Closed Cell")
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
    base_url = f"http://127.0.0.1:{port}/specimen/v3.html"
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
