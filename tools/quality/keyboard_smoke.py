import argparse
import asyncio
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import websockets


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
    async def key(self, key, modifiers=0):
        codes = {"Tab": ("Tab", 9), "Enter": ("Enter", 13), "Escape": ("Escape", 27), "/": ("Slash", 191)}
        code, virtual = codes[key]
        payload = {"key": key, "code": code, "modifiers": modifiers, "windowsVirtualKeyCode": virtual, "nativeVirtualKeyCode": virtual}
        await self.call("Input.dispatchKeyEvent", {"type": "keyDown", **payload})
        await self.call("Input.dispatchKeyEvent", {"type": "keyUp", **payload})


async def run(chrome: Path, url: str):
    with tempfile.TemporaryDirectory() as profile:
        port = 9228
        process = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            endpoint = None
            for _ in range(80):
                try:
                    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1))
                    endpoint = next(item for item in pages if item["type"] == "page")["webSocketDebuggerUrl"]
                    break
                except Exception: await asyncio.sleep(.1)
            if not endpoint: raise RuntimeError("Chrome DevTools endpoint unavailable.")
            async with websockets.connect(endpoint, max_size=8 * 1024 * 1024) as socket:
                cdp = Cdp(socket)
                await cdp.call("Page.enable"); await cdp.call("Runtime.enable"); await cdp.call("Page.bringToFront")
                await cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
                await cdp.call("Page.navigate", {"url": url}); await asyncio.sleep(1)
                await cdp.value("localStorage.setItem('ai_fleet_onboarding_complete','1'); localStorage.setItem('ai_fleet_lang','en'); location.reload()")
                await asyncio.sleep(1)
                checks = {}
                await cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 1200, "y": 800, "button": "left", "clickCount": 1})
                await cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 1200, "y": 800, "button": "left", "clickCount": 1})
                await cdp.value("document.body.setAttribute('tabindex','-1'); document.body.focus()")
                await cdp.key("Tab")
                checks["skip_link_focused"] = await cdp.value("document.activeElement?.classList.contains('skip-link')")
                await cdp.key("Enter"); await asyncio.sleep(.1)
                checks["skip_link_targets_main"] = await cdp.value("document.activeElement?.id === 'main-content'")
                await cdp.value("window.__keyboardSmoke=null; window.addEventListener('keydown',e=>window.__keyboardSmoke={key:e.key,ctrlKey:e.ctrlKey,metaKey:e.metaKey,altKey:e.altKey},{once:true,capture:true})")
                await cdp.key("/"); await asyncio.sleep(.2)
                checks["received_search_shortcut"] = await cdp.value("window.__keyboardSmoke?.key==='/'")
                checks["shortcut_focuses_search"] = await cdp.value("document.activeElement?.matches('.header-search input')")
                checks["active_after_shortcut"] = await cdp.value("document.activeElement?.outerHTML?.slice(0,200)||''")
                checks["search_active"] = await cdp.value("document.querySelector('.header-search')?.classList.contains('active')")
                checks["search_input_exists"] = await cdp.value("Boolean(document.querySelector('.header-search input'))")
                checks["direct_search_focus"] = await cdp.value("(() => { const x=document.querySelector('.header-search input'); x?.focus(); return document.activeElement===x })()")
                await cdp.key("Escape"); await asyncio.sleep(.1)
                await cdp.value("window.__renderErrors=[]; window.addEventListener('error',e=>window.__renderErrors.push(String(e.error?.stack||e.message))); window.addEventListener('unhandledrejection',e=>window.__renderErrors.push(String(e.reason?.stack||e.reason)))")
                checks["agent_created"] = await cdp.value("fetch('/api/agents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Keyboard Agent',executable:'python',version_probe_args:['--version'],health_probe_args:['--version'],invocation_args:['-c','print(1)'],capabilities:['coding'],probe_timeout_seconds:5})}).then(r=>r.ok)")
                await cdp.call("Page.reload"); await asyncio.sleep(1)
                checks["fleet_clicked"] = await cdp.value("(() => { const b=[...document.querySelectorAll('button')].find(x=>x.querySelector('.nav-text')?.textContent.trim()==='Tools'); if(!b)return false;b.click();return true })()")
                for _ in range(100):
                    if await cdp.value("[...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='Agents')"): break
                    await asyncio.sleep(.1)
                checks["agents_tab_clicked"] = await cdp.value("(() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Agents'); if(!b)return false;b.click();return true })()")
                for _ in range(100):
                    if await cdp.value("[...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='Details')"): break
                    await asyncio.sleep(.1)
                checks["agent_api_count"] = await cdp.value("fetch('/api/agents').then(r=>r.json()).then(x=>x.length)")
                checks["active_fleet_tab"] = await cdp.value("document.querySelector('.tab-strip button.active')?.textContent?.trim()||''")
                checks["fleet_error"] = await cdp.value("document.querySelector('.state-error')?.textContent?.trim()||''")
                checks["render_errors"] = await cdp.value("window.__renderErrors||[]")
                checks["fleet_query"] = await cdp.value("document.querySelector('.compact-search input')?.value||''")
                checks["page_excerpt"] = await cdp.value("document.querySelector('.fleet-page')?.textContent?.slice(0,500)||''")
                checks["agent_card_count"] = await cdp.value("document.querySelectorAll('.asset-card').length")
                checks["details_button_count"] = await cdp.value("[...document.querySelectorAll('button')].filter(x=>x.textContent.trim()==='Details').length")
                opened = await cdp.value("(() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Details'); if(!b)return false; b.focus(); b.click(); return true })()")
                checks["agent_dialog_available"] = bool(opened)
                if opened:
                    await asyncio.sleep(.2)
                    checks["dialog_initial_focus"] = await cdp.value("document.activeElement?.getAttribute('aria-label') === 'Close'")
                    await cdp.key("Tab", 1)
                    checks["dialog_shift_tab_contained"] = await cdp.value("Boolean(document.activeElement?.closest('[role=dialog]'))")
                    await cdp.key("Escape"); await asyncio.sleep(.2)
                    checks["dialog_escape_closes"] = await cdp.value("!document.querySelector('[role=dialog]')")
                    checks["dialog_restores_focus"] = await cdp.value("document.activeElement?.textContent.trim() === 'Details'")
                return checks
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--chrome", type=Path, required=True); parser.add_argument("--url", required=True); parser.add_argument("--report", type=Path, required=True); args = parser.parse_args()
    checks = asyncio.run(run(args.chrome, args.url)); args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    informational = {"active_after_shortcut", "search_active", "search_input_exists", "agent_api_count", "agent_card_count", "details_button_count", "active_fleet_tab", "fleet_error", "page_excerpt", "fleet_query", "render_errors"}
    failed = [name for name, passed in checks.items() if name not in informational and not passed]
    print(json.dumps({"checks": checks, "failed": failed}, indent=2)); return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
