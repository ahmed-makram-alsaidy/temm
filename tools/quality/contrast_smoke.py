import argparse
import asyncio
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import websockets


ROUTES = ["dashboard", "projects", "fleet", "runs", "run"]
THEMES = ["light", "dark"]


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


AUDIT = r"""(() => {
  const parse = value => { const m=value.match(/rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)(?:[, /]+([\d.]+))?\)/); return m ? [Number(m[1]),Number(m[2]),Number(m[3]),m[4]===undefined?1:Number(m[4])] : null };
  const blend = (front, back) => { const a=front[3]+back[3]*(1-front[3]); return a ? [(front[0]*front[3]+back[0]*back[3]*(1-front[3]))/a,(front[1]*front[3]+back[1]*back[3]*(1-front[3]))/a,(front[2]*front[3]+back[2]*back[3]*(1-front[3]))/a,a] : [255,255,255,1] };
  const background = element => { let layers=[], complex=false, node=element; while(node){ const style=getComputedStyle(node); if(style.backgroundImage!=='none') complex=true; const color=parse(style.backgroundColor); if(color&&color[3]>0) layers.push(color); node=node.parentElement } let result=[255,255,255,1]; for(let i=layers.length-1;i>=0;i--) result=blend(layers[i],result); return {color:result,complex} };
  const channel = value => { value/=255; return value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4) };
  const luminance = color => .2126*channel(color[0])+.7152*channel(color[1])+.0722*channel(color[2]);
  const ratio = (a,b) => { const x=luminance(a),y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05) };
  const visible = element => { const r=element.getBoundingClientRect(),s=getComputedStyle(element); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>.01&&!element.closest('[aria-hidden="true"]') };
  const results=[],complex=[]; for(const element of document.querySelectorAll('body *')){ if(!visible(element)||element.matches('script,style,svg,path'))continue; const text=[...element.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(' ').trim(); if(!text)continue; const style=getComputedStyle(element); const foreground=parse(style.color); if(!foreground)continue; const bg=background(element); if(bg.complex){ complex.push({tag:element.tagName,className:String(element.className||''),text:text.slice(0,80)}); continue } const effective=blend(foreground,bg.color); const size=parseFloat(style.fontSize),weight=parseInt(style.fontWeight)||400; const large=size>=24||(size>=18.66&&weight>=700); const required=large?3:4.5,measured=ratio(effective,bg.color); if(measured+0.01<required) results.push({tag:element.tagName,className:String(element.className||''),text:text.slice(0,80),font_size:size,font_weight:weight,foreground:style.color,background:`rgb(${bg.color.slice(0,3).map(Math.round).join(', ')})`,ratio:Number(measured.toFixed(2)),required}) }
  return {failures:results.slice(0,200),failure_count:results.length,complex_background_count:complex.length,complex_backgrounds:complex.slice(0,30)};
})()"""


async def run(chrome: Path, url: str):
    with tempfile.TemporaryDirectory() as profile:
        port = 9230
        process = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            endpoint = None
            for _ in range(80):
                try:
                    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1)); endpoint = next(item for item in pages if item["type"] == "page")["webSocketDebuggerUrl"]; break
                except Exception: await asyncio.sleep(.1)
            if not endpoint: raise RuntimeError("Chrome DevTools endpoint unavailable.")
            async with websockets.connect(endpoint, max_size=16*1024*1024) as socket:
                cdp=Cdp(socket); await cdp.call("Page.enable"); await cdp.call("Runtime.enable"); await cdp.call("Page.bringToFront"); await cdp.call("Emulation.setDeviceMetricsOverride", {"width":1440,"height":900,"deviceScaleFactor":1,"mobile":False}); await cdp.call("Page.navigate", {"url":url}); await asyncio.sleep(1)
                await cdp.value("localStorage.setItem('ai_fleet_onboarding_complete','1'); localStorage.setItem('ai_fleet_lang','en'); location.reload()"); await asyncio.sleep(1)
                report=[]
                for theme in THEMES:
                    await cdp.value(f"localStorage.setItem('ai_fleet_theme',{json.dumps(theme)}); document.documentElement.dataset.theme={json.dumps(theme)}")
                    for route in ROUTES:
                        selector=".new-task-button" if route=="run" else f"[data-route='{route}']"
                        clicked=await cdp.value(f"(() => {{ const x=document.querySelector({json.dumps(selector)}); if(x)x.click(); return Boolean(x) }})()")
                        await asyncio.sleep(.35)
                        result=await cdp.value(AUDIT)
                        report.append({"theme":theme,"route":route,"navigation_control_found":clicked,**result})
                return report
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--chrome",type=Path,required=True);parser.add_argument("--url",required=True);parser.add_argument("--report",type=Path,required=True);args=parser.parse_args()
    report=asyncio.run(run(args.chrome,args.url));args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2),encoding="utf-8")
    failures=sum(item["failure_count"] for item in report);print(json.dumps({"cases":len(report),"contrast_failures":failures,"complex_backgrounds":sum(item["complex_background_count"] for item in report),"report":str(args.report)},indent=2));return 1 if failures else 0


if __name__=="__main__":raise SystemExit(main())
