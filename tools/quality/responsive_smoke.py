import argparse
import asyncio
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets


VIEWPORTS = [("desktop", 1440, 900), ("laptop", 1024, 768), ("tablet", 768, 1024), ("mobile", 390, 844)]
ROUTES = ["dashboard", "projects", "fleet", "runs", "run"]


class Cdp:
    def __init__(self, socket): self.socket = socket; self.sequence = 0
    async def call(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        await self.socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(await self.socket.recv())
            if response.get("id") == request_id:
                if "error" in response: raise RuntimeError(response["error"])
                return response.get("result", {})


async def run(chrome: Path, url: str, output: Path, language: str):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        port = 9227
        process = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            endpoint = None
            for _ in range(80):
                try:
                    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1))
                    page = next(item for item in pages if item["type"] == "page")
                    endpoint = page["webSocketDebuggerUrl"]
                    break
                except Exception:
                    await asyncio.sleep(.1)
            if not endpoint: raise RuntimeError("Chrome DevTools endpoint did not become ready.")
            async with websockets.connect(endpoint, max_size=16 * 1024 * 1024) as socket:
                cdp = Cdp(socket)
                await cdp.call("Page.enable")
                await cdp.call("Runtime.enable")
                await cdp.call("Page.navigate", {"url": url})
                await asyncio.sleep(1)
                await cdp.call("Runtime.evaluate", {"expression": f"localStorage.setItem('ai_fleet_onboarding_complete','1'); localStorage.setItem('ai_fleet_lang',{json.dumps(language)}); location.reload()"})
                await asyncio.sleep(1)
                results = []
                for name, width, height in VIEWPORTS:
                    await cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                    for route in ROUTES:
                        selector = ".new-task-button" if route == "run" else f"[data-route='{route}']"
                        expression = f"""(() => {{ const target=document.querySelector({json.dumps(selector)}); if(target) target.click(); return Boolean(target); }})()"""
                        clicked = (await cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True}))["result"].get("value", False)
                        await asyncio.sleep(.25)
                        metrics_expression = """(() => { const root=document.documentElement; const body=document.body; const offenders=[...document.querySelectorAll('*')].filter(el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); const ancestorState=(()=>{let p=el.parentElement;while(p){const ps=getComputedStyle(p);if(ps.position==='fixed')return 'fixed';if(ps.overflowX==='auto'||ps.overflowX==='scroll')return 'scroll';p=p.parentElement}return ''})(); return r.right > innerWidth + 1 && s.position !== 'fixed' && !ancestorState && s.overflowX !== 'auto' && s.overflowX !== 'scroll'; }).slice(0,20).map(el => ({tag:el.tagName, cls:el.className, right:Math.round(el.getBoundingClientRect().right)})); const main=document.querySelector('main'); return {viewport_width:innerWidth, scroll_width:Math.max(root.scrollWidth,body.scrollWidth), viewport_height:innerHeight, scroll_height:Math.max(root.scrollHeight,body.scrollHeight), routeHeading:document.querySelector('h1')?.textContent||'', mainVisible:Boolean(main&&main.getBoundingClientRect().width>0), document_dir:document.documentElement.dir, document_lang:document.documentElement.lang, offenders}; })()"""
                        metrics = (await cdp.call("Runtime.evaluate", {"expression": metrics_expression, "returnByValue": True}))["result"]["value"]
                        screenshot = await cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                        screenshot_name = f"{name}-{route}.png"
                        (output / screenshot_name).write_bytes(base64.b64decode(screenshot["data"]))
                        results.append({"name": f"{name}:{route}", "route": route, "expected_language": language, "navigation_control_found": clicked, "screenshot_id": screenshot_name, **metrics})
                return results
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--language", choices=["en", "ar"], default="en")
    args = parser.parse_args()
    results = asyncio.run(run(args.chrome, args.url, args.output, args.language))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = [item for item in results if item["scroll_width"] > item["viewport_width"] or item["offenders"] or not item["mainVisible"]]
    print(json.dumps({"viewports": len(results), "failed": len(failed), "report": str(args.report)}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
