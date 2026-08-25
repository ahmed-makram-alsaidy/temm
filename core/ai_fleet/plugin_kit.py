import re
from pathlib import Path
import yaml
from .plugin_protocol import PluginManifest
TYPE_MAP={"agent":"agent","provider":"provider","skill":"skill","research":"research","asset":"asset_source","gate":"quality_gate"}
DEFAULTS={"agent":(["general"],["detect","version","health","start","stream","cancel"]),"provider":(["general"],["auth","health","start","stream","cancel","usage","quota"]),"skill":(["general"],["health","start"]),"research":(["research","network"],["health","start"]),"asset":(["asset_search","network"],["health","start"]),"gate":(["quality_gate"],["health","start"])}
class PluginKit:
 def scaffold(self,parent:Path,plugin_id:str,kind:str):
  if kind not in TYPE_MAP or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}",plugin_id):raise ValueError("Plugin scaffold identity is invalid.")
  folder=parent/plugin_id
  if folder.exists():raise FileExistsError("Plugin folder already exists.")
  capabilities,methods=DEFAULTS[kind];permissions=["network"] if kind in {"research","asset"} else []
  manifest={"id":plugin_id,"name":plugin_id.replace("-"," ").title(),"version":"0.1.0","protocol":"1.0","type":TYPE_MAP[kind],"platforms":["windows","linux","macos"],"capabilities":capabilities,"permissions":permissions,"entrypoint":"adapter.py","rpc_methods":methods};PluginManifest.parse(manifest)
  folder.mkdir(parents=False);(folder/"manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8");(folder/"adapter.py").write_text("def handle(request):\n    return {'ok': False, 'error': {'code': 'not_implemented', 'message': 'Implement this plugin method.'}}\n",encoding="utf-8");(folder/"test_adapter.py").write_text("from adapter import handle\n\ndef test_not_implemented():\n    assert handle({'method': 'health'})['error']['code'] == 'not_implemented'\n",encoding="utf-8");return folder
plugin_kit=PluginKit()
