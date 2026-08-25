import argparse
import asyncio
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import websockets


ROUTES = ["dashboard", "projects", "fleet", "runs", "run", "settings"]
INTERACTIVE = {"button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio", "switch", "tab", "menuitem", "slider", "spinbutton"}


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
    async def value(self, expression): return (await self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}))["result"].get("value")


async def audit(cdp, language, route):
    selector = ".new-task-button" if route == "run" else f"[data-route='{route}']"
    clicked = await cdp.value(f"(() => {{ const x=document.querySelector({json.dumps(selector)}); if(x)x.click(); return Boolean(x) }})()")
    await asyncio.sleep(.4)
    nodes = (await cdp.call("Accessibility.getFullAXTree"))["nodes"]
    exposed = [node for node in nodes if not node.get("ignored")]
    roles = [node.get("role", {}).get("value", "") for node in exposed]
    unnamed = []
    for node in exposed:
        role = node.get("role", {}).get("value", "")
        name = str(node.get("name", {}).get("value", "")).strip()
        if role in INTERACTIVE and not name:
            unnamed.append({"role": role, "node_id": node.get("nodeId")})
    headings = [node for node in exposed if node.get("role", {}).get("value") == "heading" and str(node.get("name", {}).get("value", "")).strip()]
    mains = roles.count("main")
    navigation = [node for node in exposed if node.get("role", {}).get("value") == "navigation" and str(node.get("name", {}).get("value", "")).strip()]
    return {"language": language, "route": route, "navigation_control_found": clicked, "main_count": mains, "named_navigation_count": len(navigation), "named_heading_count": len(headings), "unnamed_interactive": unnamed, "passed": clicked and mains == 1 and bool(navigation) and bool(headings) and not unnamed}


async def run(chrome: Path, url: str):
    with tempfile.TemporaryDirectory() as profile:
        port = 9231
        process = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            endpoint = None
            for _ in range(80):
                try:
                    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1)); endpoint = next(item for item in pages if item["type"] == "page")["webSocketDebuggerUrl"]; break
                except Exception: await asyncio.sleep(.1)
            if not endpoint: raise RuntimeError("Chrome DevTools endpoint unavailable.")
            async with websockets.connect(endpoint, max_size=16*1024*1024) as socket:
                cdp=Cdp(socket); await cdp.call("Page.enable"); await cdp.call("Runtime.enable"); await cdp.call("Accessibility.enable"); await cdp.call("Page.bringToFront"); await cdp.call("Emulation.setDeviceMetricsOverride", {"width":1440,"height":900,"deviceScaleFactor":1,"mobile":False}); await cdp.call("Page.navigate", {"url":url}); await asyncio.sleep(1)
                results=[]
                for language in ("en", "ar"):
                    await cdp.value(f"localStorage.setItem('ai_fleet_onboarding_complete','1');localStorage.setItem('ai_fleet_lang',{json.dumps(language)});location.reload()")
                    await asyncio.sleep(1)
                    for route in ROUTES: results.append(await audit(cdp, language, route))
                await cdp.value("localStorage.setItem('ai_fleet_lang','en');location.reload()")
                await asyncio.sleep(1)
                created = await cdp.value("fetch('/api/agents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'AX Agent',executable:'python',version_probe_args:['--version'],health_probe_args:['--version'],invocation_args:['-c','print(1)'],capabilities:['coding'],probe_timeout_seconds:5})}).then(r=>r.ok||r.status===409)")
                await cdp.value("document.querySelector(\"[data-route='fleet']\")?.click()")
                await asyncio.sleep(.7)
                await cdp.value("[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Agents')?.click()")
                for _ in range(100):
                    if await cdp.value("[...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='Details')"): break
                    await asyncio.sleep(.1)
                opened = await cdp.value("(() => {const x=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Details');if(!x)return false;x.click();return true})()")
                await asyncio.sleep(.2)
                nodes=(await cdp.call("Accessibility.getFullAXTree"))["nodes"]
                dialogs=[node for node in nodes if not node.get("ignored") and node.get("role",{}).get("value")=="dialog"]
                dialog_names=[str(node.get("name",{}).get("value","")).strip() for node in dialogs]
                results.append({"language":"en","route":"agent-dialog","fixture_created":created,"dialog_opened":opened,"dialog_count":len(dialogs),"dialog_names":dialog_names,"passed":created and opened and len(dialogs)==1 and bool(dialog_names[0])})
                return results
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--chrome",type=Path,required=True);parser.add_argument("--url",required=True);parser.add_argument("--report",type=Path,required=True);args=parser.parse_args()
    results=asyncio.run(run(args.chrome,args.url));args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(results,indent=2),encoding="utf-8");failed=[item for item in results if not item["passed"]];print(json.dumps({"cases":len(results),"failed":len(failed),"report":str(args.report)},indent=2));return 1 if failed else 0


if __name__=="__main__":raise SystemExit(main())
