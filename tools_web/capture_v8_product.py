"""Drive the REAL TEMM product (backend on :8787) through Runs -> RunDetails.

No query parameters, no specimen routes: the harness launches the actual
application, clicks the sidebar like a user, and proves the V8 hierarchy on
live data from the local SQLite store.
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
DEFAULT_OUTPUT = ROOT / "docs" / "specimen-v8"
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
    profile = Path(tempfile.mkdtemp(prefix="temm-real-"))
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

    async def shot(cdp: Cdp, name: str) -> dict[str, object]:
        screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path = output / f"{name}.png"
        path.write_bytes(base64.b64decode(screenshot["data"]))
        return {"name": name, "screenshot": path.name, "bytes": path.stat().st_size}

    try:
        endpoint = await devtools_endpoint(debug_port)
        async with websockets.connect(endpoint, max_size=24 * 1024 * 1024) as websocket:
            cdp = Cdp(websocket)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
            })

            # 1. The real product, cold, no parameters.
            await cdp.call("Page.navigate", {"url": PRODUCT + "/"})
            await asyncio.sleep(2.5)
            await cdp.call("Runtime.evaluate", {"expression": "document.fonts.ready.then(() => true)", "awaitPromise": True, "returnByValue": True})

            # 2. Click the Runs nav item like a user.
            clicked = await cdp.call("Runtime.evaluate", {
                "expression": """(() => {
                  const item = [...document.querySelectorAll('.nav-item')].find((el) => /Runs|عمليات التشغيل/.test(el.textContent || ''));
                  if (!item) return 'nav-missing';
                  item.click();
                  return 'clicked';
                })()""",
                "returnByValue": True,
            })
            await asyncio.sleep(2.0)

            runs_metrics = await cdp.call("Runtime.evaluate", {
                "expression": """(() => {
                  const rows = [...document.querySelectorAll('.temm-v8-run-row')];
                  const withProject = document.querySelectorAll('.temm-v8-run-project').length;
                  const url = location.href;
                  return {
                    url,
                    navClick: 'ok',
                    rows: rows.length,
                    tables: document.querySelectorAll('table').length,
                    projectContextAtL1: withProject,
                    sampleSentence: document.querySelector('.temm-v8-run-sentence')?.textContent?.slice(0, 160) ?? null,
                    acceptanceWords: rows.map((r) => r.textContent || '').join(' ').match(/\b(accepted|verified)\b/i)?.[0] ?? null,
                    scrollWidth: document.documentElement.scrollWidth,
                    viewportWidth: innerWidth,
                  };
                })()""",
                "returnByValue": True,
            })
            metrics = runs_metrics["result"]["value"]
            metrics.update(await shot(cdp, "real-product-runs"))
            results.append(metrics)
            print("runs page:", json.dumps(metrics, indent=1)[:600])

            # 3. Open a COMPLETED run row (real navigation into RunWorkspace).
            await cdp.call("Runtime.evaluate", {
                "expression": """document.querySelector(".temm-v8-run-row[data-outcome='completed'] .temm-v8-run-main")?.click()""",
                "returnByValue": True,
            })
            await asyncio.sleep(3.0)

            # 4. Open the L3 technical receipt disclosure.
            await cdp.call("Runtime.evaluate", {
                "expression": "[...document.querySelectorAll('.temm-v8-receipt-details summary, .technical-card summary')].forEach((s) => s.click())",
                "returnByValue": True,
            })
            await asyncio.sleep(0.4)

            detail_metrics = await cdp.call("Runtime.evaluate", {
                "expression": """(() => {
                  const narrative = document.querySelector('.temm-v8-narrative');
                  const verdict = document.querySelector('.temm-v8-narrative-verdict')?.textContent || '';
                  const storyFirst = document.querySelector('.run-main-column')?.firstElementChild?.className || '';
                  const receiptOpen = document.querySelectorAll('.temm-v8-receipt-details[open], .technical-card[open]').length;
                  const bodyText = document.body.innerText;
                  return {
                    url: location.href,
                    narrativeVisible: Boolean(narrative),
                    intentFirst: String(storyFirst).includes('temm-v8-narrative'),
                    timelineAbsent: !document.querySelector('.run-timeline'),
                    verdictText: verdict.slice(0, 120),
                    acceptanceWords: verdict.match(/\\b(accepted|verified)\\b/i)?.[0] ?? null,
                    receiptOpen,
                    eventLogPresent: bodyText.includes('Event log') || bodyText.includes('أحداث السجل'),
                    scrollWidth: document.documentElement.scrollWidth,
                    viewportWidth: innerWidth,
                  };
                })()""",
                "returnByValue": True,
            })
            metrics = detail_metrics["result"]["value"]
            metrics.update(await shot(cdp, "real-product-run-details"))
            results.append(metrics)
            print("details page:", json.dumps(metrics, indent=1)[:600])
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
    runs = results[0]
    details = results[1]
    if "specimen" in str(runs.get("url")) or "?" in str(runs.get("url")):
        failures.append("runs page used a parameterised or specimen URL")
    if int(runs.get("rows", 0)) == 0:
        failures.append("no real run rows rendered")
    if int(runs.get("projectContextAtL1", 0)) == 0:
        failures.append("project context missing at L1")
    if runs.get("tables"):
        failures.append("a data table rendered on Runs")
    if runs.get("acceptanceWords"):
        failures.append(f"acceptance vocabulary on Runs: {runs.get('acceptanceWords')}")
    if int(runs.get("scrollWidth", 0)) > int(runs.get("viewportWidth", 0)):
        failures.append("horizontal overflow on Runs")
    if not details.get("intentFirst"):
        failures.append("the causal story does not lead the completed run page")
    if not details.get("timelineAbsent"):
        failures.append("the running recap card lingers on a terminal run")
    if not details.get("narrativeVisible"):
        failures.append("RunDetails narrative missing on the real run page")
    if not details.get("receiptOpen"):
        failures.append("L3 receipt did not open on the real run page")
    if details.get("acceptanceWords"):
        failures.append(f"acceptance vocabulary in the verdict: {details.get('acceptanceWords')}")
    if int(details.get("scrollWidth", 0)) > int(details.get("viewportWidth", 0)):
        failures.append("horizontal overflow on the run page")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-backend", action="store_true", help="assume the product is already serving :8787")
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
        else:
            with urllib.request.urlopen(f"{PRODUCT}/api/projects", timeout=2) as response:
                assert response.status == 200
        results = asyncio.run(capture(args.chrome, args.output))
    finally:
        if backend is not None:
            backend.terminate()
            try:
                backend.wait(timeout=10)
            except subprocess.TimeoutExpired:
                backend.kill()

    failures = failed_checks(results)
    report = args.output / "real-product-report.json"
    report.write_text(json.dumps({"shots": results, "failures": failures}, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(results), "failed": len(failures), "report": str(report)}, indent=2))
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
