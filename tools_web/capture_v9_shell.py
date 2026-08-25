"""Drive the REAL TEMM product shell (backend on :8787) through the V9 route.

Normal launch -> Projects (default) -> Runs -> a run's detail (Runs stays
current) -> Tools -> Settings -> back to Projects, plus RTL and mobile shell
states. No query parameters; the shell is driven by real clicks.
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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v9"
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


SHELL_STATE = """(() => {
  const current = document.querySelector('.nav-item.active');
  const texts = [...document.querySelectorAll('.sidebar *, .topbar *')]
    .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
    .map((el) => parseFloat(getComputedStyle(el).fontSize))
    .filter((s) => Number.isFinite(s) && s > 0);
  return {
    currentRoute: current?.getAttribute('data-route') ?? null,
    ariaCurrent: current?.getAttribute('aria-current') ?? null,
    activeColor: current ? getComputedStyle(current).color : null,
    activeBackground: current ? getComputedStyle(current).backgroundColor : null,
    groups: document.querySelectorAll('.nav-list[data-group]').length,
    systemLabel: [...document.querySelectorAll('.nav-label')].some((el) => /System|النظام/.test(el.textContent || '')),
    statusTone: document.querySelector('.sidebar-status')?.getAttribute('data-tone') ?? null,
    smallestFontPx: texts.length ? Math.min(...texts) : null,
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: innerWidth,
    direction: document.documentElement.dir,
  };
})()"""


async def capture(chrome: Path, output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="temm-v9-"))
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

    async def click_nav(cdp: Cdp, route: str) -> None:
        await cdp.call("Runtime.evaluate", {
            "expression": f"""document.querySelector('.nav-item[data-route="{route}"]')?.click()""",
            "returnByValue": True,
        })
        await asyncio.sleep(1.6)

    async def shot(cdp: Cdp, cdp_name: str, state: dict[str, object]) -> dict[str, object]:
        screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path = output / f"{cdp_name}.png"
        path.write_bytes(base64.b64decode(screenshot["data"]))
        return {"name": cdp_name, "screenshot": path.name, **state}

    try:
        endpoint = await devtools_endpoint(debug_port)
        async with websockets.connect(endpoint, max_size=24 * 1024 * 1024) as websocket:
            cdp = Cdp(websocket)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
            })

            # English shell for the main walk (fresh profile defaults to Arabic).
            await cdp.call("Page.navigate", {"url": PRODUCT + "/"})
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'en'); location.reload();",
            })
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {"expression": "document.fonts.ready.then(() => true)", "awaitPromise": True, "returnByValue": True})

            # 1. Cold launch: Projects is the current location.
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-default-projects", state))

            # 2. Runs.
            await click_nav(cdp, "runs")
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-runs", state))

            # 3. Open a completed run: the shell must keep Runs current.
            await cdp.call("Runtime.evaluate", {
                "expression": """document.querySelector(".temm-v8-run-row[data-outcome='completed'] .temm-v8-run-main")?.click()""",
                "returnByValue": True,
            })
            await asyncio.sleep(2.5)
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-run-detail-runs-current", state))

            # 4. Tools. 5. Settings. 6. Back to Projects.
            await click_nav(cdp, "fleet")
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-tools", state))

            await click_nav(cdp, "settings")
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-settings", state))

            await click_nav(cdp, "projects")
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-back-to-projects", state))

            # 7. RTL shell.
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'ar'); location.reload();",
            })
            await asyncio.sleep(2.5)
            await click_nav(cdp, "runs")
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-rtl-runs", state))

            # 8. Mobile shell: drawer navigation stays reachable.
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
            })
            await cdp.call("Runtime.evaluate", {
                "expression": "localStorage.setItem('ai_fleet_lang', 'en'); location.reload();",
            })
            await asyncio.sleep(2.5)
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            results.append(await shot(cdp, "v9-mobile-closed", state))
            await cdp.call("Runtime.evaluate", {
                "expression": "document.querySelector('.menu-toggle')?.click()",
                "returnByValue": True,
            })
            await asyncio.sleep(0.8)
            state = (await cdp.call("Runtime.evaluate", {"expression": SHELL_STATE, "returnByValue": True}))["result"]["value"]
            drawer_open = await cdp.call("Runtime.evaluate", {
                "expression": "Boolean(document.querySelector('.sidebar.open'))",
                "returnByValue": True,
            })
            state["drawerOpen"] = drawer_open["result"]["value"]
            results.append(await shot(cdp, "v9-mobile-drawer", state))
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
    expected_current = [
        ("v9-default-projects", "projects"), ("v9-runs", "runs"), ("v9-run-detail-runs-current", "runs"),
        ("v9-tools", "fleet"), ("v9-settings", "settings"), ("v9-back-to-projects", "projects"),
        ("v9-rtl-runs", "runs"), ("v9-mobile-closed", "runs"),
    ]
    by_name = {str(item["name"]): item for item in results}
    for name, route in expected_current:
        item = by_name.get(name)
        if not item:
            failures.append(f"{name}: capture missing")
            continue
        if item.get("currentRoute") != route:
            failures.append(f"{name}: active location is {item.get('currentRoute')!r}, expected {route!r}")
        if item.get("ariaCurrent") != "page":
            failures.append(f"{name}: aria-current missing on the active item")
        if item.get("groups") != 2:
            failures.append(f"{name}: navigation groups missing")
        if not item.get("systemLabel"):
            failures.append(f"{name}: System group label missing")
        if item.get("statusTone") not in ("neutral", "attention"):
            failures.append(f"{name}: system status tone missing")
        smallest = item.get("smallestFontPx")
        if smallest is not None and float(smallest) < 11.5:
            failures.append(f"{name}: shell text below the 12px floor ({smallest})")
        if int(item.get("scrollWidth", 0)) > int(item.get("viewportWidth", 0)):
            failures.append(f"{name}: horizontal overflow")
    rtl = by_name.get("v9-rtl-runs")
    if rtl and rtl.get("direction") != "rtl":
        failures.append("v9-rtl-runs: document direction is not rtl")
    mobile = by_name.get("v9-mobile-drawer")
    if mobile and not mobile.get("drawerOpen"):
        failures.append("v9-mobile-drawer: the navigation drawer did not open")
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
