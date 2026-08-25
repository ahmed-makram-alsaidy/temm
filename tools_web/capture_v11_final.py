"""Drive the REAL TEMM product for final V11 acceptance proof."""

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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v11"
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
    profile = Path(tempfile.mkdtemp(prefix="temm-v11-"))
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
            # Start at root
            await cdp.call("Page.navigate", {"url": PRODUCT + "/"})
            await asyncio.sleep(2.5)

            async def eval_js(expr: str):
                res = await cdp.call("Runtime.evaluate", {
                    "expression": expr,
                    "returnByValue": True
                })
                if "exceptionDetails" in res["result"]:
                    print("JS Error:", res["result"]["exceptionDetails"])
                return res["result"].get("value")

            async def shoot(name: str):
                screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                path = output / f"{name}.png"
                path.write_bytes(base64.b64decode(screenshot["data"]))
                
                # Check for overflow and active route
                state = await eval_js("""(() => {
                    const active = document.querySelector('.nav-item.active');
                    return {
                        route: active ? active.getAttribute('data-route') : null,
                        overflow: document.documentElement.scrollWidth > innerWidth
                    };
                })()""")
                
                results.append({"name": name, "screenshot": path.name, "state": state})
                print(f"ok   {name:30s} (route: {state['route']}, overflow: {state['overflow']})")

            # 1. Projects default launch
            await shoot("v11-01-projects-launch")

            # 2. Open real project -> Project Workspace
            # Click first project
            await eval_js("document.querySelector('.project-list > button')?.click()")
            await asyncio.sleep(2)
            await shoot("v11-02-project-workspace")

            # 3. Acceptance / Evidence / Closed cell
            # Try clicking on an accepted task in the lattice to show evidence/cell
            await eval_js("document.querySelector('.temm-v3-lattice-task[data-state=\"accepted\"]')?.click()")
            await asyncio.sleep(1)
            await shoot("v11-03-acceptance-cell")

            # 4. Runs
            await eval_js("document.querySelector('.nav-item[data-route=\"runs\"]')?.click()")
            await asyncio.sleep(1.5)
            await shoot("v11-04-runs")

            # 5. RunDetails + L3 receipt
            # Click first run
            await eval_js("document.querySelector('.temm-v8-run-main')?.click()")
            await asyncio.sleep(1.5)
            # Expand technical receipt
            await eval_js("document.querySelector('.temm-v8-receipt-details > summary')?.click()")
            await asyncio.sleep(0.5)
            await shoot("v11-05-run-details-receipt")

            # 6. Tools (fleet)
            await eval_js("document.querySelector('.nav-item[data-route=\"fleet\"]')?.click()")
            await asyncio.sleep(1)
            await shoot("v11-06-tools")

            # 7. Workspaces
            await eval_js("document.querySelector('.nav-item[data-route=\"workspaces\"]')?.click()")
            await asyncio.sleep(1.5)
            await shoot("v11-07-workspaces")

            # 8. Automation
            await eval_js("document.querySelector('.nav-item[data-route=\"automation\"]')?.click()")
            await asyncio.sleep(1.5)
            await shoot("v11-08-automation")

            # 9. Insights
            await eval_js("document.querySelector('.nav-item[data-route=\"insights\"]')?.click()")
            await asyncio.sleep(1.5)
            await shoot("v11-09-insights")

            # 10. Model Lab
            await eval_js("document.querySelector('.nav-item[data-route=\"model_lab\"]')?.click()")
            await asyncio.sleep(1.5)
            await shoot("v11-10-model-lab")

            # 11. System Overview (Dashboard)
            await eval_js("document.querySelector('.nav-item[data-route=\"dashboard\"]')?.click()")
            await asyncio.sleep(1)
            await shoot("v11-11-system-overview")

            # 12. Settings
            await eval_js("document.querySelector('.nav-item[data-route=\"settings\"]')?.click()")
            await asyncio.sleep(1)
            await shoot("v11-12-settings")

            # 13. Command Console
            await eval_js("document.querySelector('.nav-item[data-route=\"console\"]')?.click()")
            await asyncio.sleep(1)
            await shoot("v11-13-command-console")

            # 14. Back to projects
            await eval_js("document.querySelector('.nav-item[data-route=\"projects\"]')?.click()")
            await asyncio.sleep(1.5)

            # 15. RTL Test
            await eval_js("localStorage.setItem('ai_fleet_lang', 'ar'); location.reload();")
            await asyncio.sleep(2)
            await shoot("v11-15-rtl-projects")

            # 16. Mobile test
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
            })
            await eval_js("localStorage.setItem('ai_fleet_lang', 'en'); location.reload();")
            await asyncio.sleep(2)
            # Open drawer
            await eval_js("document.querySelector('.menu-toggle')?.click()")
            await asyncio.sleep(0.5)
            await shoot("v11-16-mobile-drawer")

            return results
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
        shutil.rmtree(profile, ignore_errors=True)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-backend", action="store_true")
    args = parser.parse_args()

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

    report = args.output / "report.json"
    report.write_text(json.dumps({"shots": results}, indent=2), encoding="utf-8")
    
    failed = [r for r in results if r.get('state', {}).get('overflow')]
    if failed:
        print("FAILURES: Horizontal overflow detected in", [f['name'] for f in failed])
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
