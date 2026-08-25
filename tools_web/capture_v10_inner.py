"""Drive the REAL TEMM product (backend on :8787) through every V10 surface.

Projects -> Runs -> Tools -> Workspaces -> Automation -> Insights -> Model Lab
-> System overview -> Settings -> Command console -> Projects. No QA params;
every hop is a real sidebar click. Captures desktop, RTL, and mobile states.
"""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v10"
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PRODUCT = "http://127.0.0.1:8787"


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


def wait_for_product(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The TEMM backend exited during startup")
        try:
            with urllib.request.urlopen(f"{PRODUCT}/api/projects", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("The TEMM backend did not become ready on :8787")


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


async def capture(chrome: Path, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v10-"))
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
    results: list[dict[str, object]] = []
    try:
        endpoint = await devtools_endpoint(debug_port)
        async with websockets.connect(endpoint, max_size=24 * 1024 * 1024) as websocket:
            cdp = Cdp(websocket)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
            })
            await cdp.call("Page.navigate", {"url": PRODUCT + "/"})
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'en'); location.reload();",
            })
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {"expression": "document.fonts.ready.then(() => true)", "awaitPromise": True, "returnByValue": True})

            async def visit(route: str, name: str, settle: float = 1.8) -> None:
                await cdp.call("Runtime.evaluate", {
                    "expression": f"""document.querySelector('.nav-item[data-route="{route}"]')?.click()""",
                    "returnByValue": True,
                })
                await asyncio.sleep(settle)
                state = (await cdp.call("Runtime.evaluate", {
                    "expression": """(() => ({
                      currentRoute: document.querySelector('.nav-item.active')?.getAttribute('data-route') ?? null,
                      h1: document.querySelector('.page-stage h1, main h1')?.textContent?.slice(0, 60) ?? null,
                      smallest: (() => {
                        const sizes = [...document.querySelectorAll('.page-stage *')]
                          .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
                          .map((el) => parseFloat(getComputedStyle(el).fontSize))
                          .filter((s) => Number.isFinite(s) && s > 0);
                        return sizes.length ? Math.min(...sizes) : null;
                      })(),
                      overflow: document.documentElement.scrollWidth > innerWidth,
                      greenLeak: (() => {
                        const offenders = [...document.querySelectorAll('.page-stage .status-badge, .page-stage .fleet-badge, .page-stage .status-dot')]
                          .filter((el) => {
                            const c = getComputedStyle(el).backgroundColor;
                            const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                            return m ? (+m[1] < 120 && +m[2] > 130 && +m[3] < 120) : false;
                          }).length;
                        return offenders;
                      })(),
                    }))()""",
                    "returnByValue": True,
                }))["result"]["value"]
                screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                path = output / f"{name}.png"
                path.write_bytes(base64.b64decode(screenshot["data"]))
                results.append({"name": name, "screenshot": path.name, **state})
                print(f"ok   {name:34s} route={state['currentRoute']} minFont={state['smallest']}")

            # The full real-product walk.
            await visit("projects", "v10-projects")
            await visit("runs", "v10-runs")
            await visit("fleet", "v10-tools", settle=2.4)
            await visit("workspaces", "v10-workspaces")
            await visit("automation", "v10-automation", settle=2.2)
            await visit("insights", "v10-insights", settle=2.2)
            await visit("model_lab", "v10-model-lab", settle=2.2)
            await visit("dashboard", "v10-system-overview")
            await visit("settings", "v10-settings", settle=2.2)
            await visit("console", "v10-command-console")
            await visit("projects", "v10-back-to-projects")

            # RTL pass over the structurally changed surface + one light one.
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'ar'); location.reload();",
            })
            await asyncio.sleep(2.5)
            await visit("dashboard", "v10-rtl-system-overview")
            await visit("fleet", "v10-rtl-tools", settle=2.4)

            # Mobile recomposition of the changed surfaces.
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
            })
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'en'); location.reload();",
            })
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {
                "expression": """document.querySelector('.menu-toggle')?.click()""",
                "returnByValue": True,
            })
            await asyncio.sleep(0.6)
            await cdp.call("Runtime.evaluate", {
                "expression": """[...document.querySelectorAll('.nav-item')].find((el) => el.getAttribute('data-route') === 'dashboard')?.click()""",
                "returnByValue": True,
            })
            await asyncio.sleep(1.8)
            await visit("dashboard", "v10-mobile-system-overview", settle=0.4)
            return results
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
        shutil.rmtree(profile, ignore_errors=True)


def failed_checks(results: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for item in results:
        name = str(item["name"])
        if item.get("overflow"):
            failures.append(f"{name}: horizontal overflow")
        smallest = item.get("smallest")
        if smallest is not None and float(smallest) < 11.5:
            failures.append(f"{name}: text below the 12px floor ({smallest})")
        if item.get("greenLeak"):
            failures.append(f"{name}: {item.get('greenLeak')} green status badges/dots in the page body")
        if item.get("currentRoute") is None:
            failures.append(f"{name}: shell lost the active location")
    overview = next((item for item in results if item["name"] == "v10-system-overview"), None)
    if overview and "System overview" not in str(overview.get("h1")):
        failures.append(f"system overview heading wrong: {overview.get('h1')}")
    back = next((item for item in results if item["name"] == "v10-back-to-projects"), None)
    if back and back.get("currentRoute") != "projects":
        failures.append("the walk did not return to Projects")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-backend", action="store_true")
    args = parser.parse_args()
    if not args.chrome.is_file():
        raise FileNotFoundError(f"Chrome not found: {args.chrome}")

    backend = None
    if not args.skip_backend:
        backend = subprocess.Popen(
            ["python", "run.py"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        if backend is not None:
            wait_for_product(backend)
        results = asyncio.run(capture(args.chrome, args.output))
    finally:
        if backend is not None:
            backend.terminate()
            try:
                backend.wait(timeout=10)
            except subprocess.TimeoutExpired:
                backend.kill()

    failures = failed_checks(results)
    report = args.output / "report.json"
    report.write_text(json.dumps({"shots": results, "failures": failures}, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(results), "failed": len(failures), "report": str(report)}, indent=2))
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
