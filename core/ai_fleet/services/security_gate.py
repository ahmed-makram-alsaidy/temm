import re
from pathlib import Path
from typing import Any,Dict,List
class SecurityGateService:
 def scan(self,root:Path,advisories:List[Dict[str,Any]]|None=None):
  findings=[];patterns=[("secret_api_key",re.compile(r"\b(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}",re.I),"critical"),("dangerous_cors",re.compile(r"allow_origins\s*=\s*\[?['\"]\*",re.I),"high"),("debug_enabled",re.compile(r"\bdebug\s*=\s*(?:true|1)\b",re.I),"medium")]
  for path in sorted(root.rglob("*")):
   if not path.is_file() or path.stat().st_size>1024*1024 or any(part in {".git","node_modules","dist","build"} for part in path.parts):continue
   try:text=path.read_text(encoding="utf-8")
   except (UnicodeError,OSError):continue
   for line_no,line in enumerate(text.splitlines(),1):
    for rule,pattern,severity in patterns:
     if pattern.search(line):findings.append({"rule":rule,"severity":severity,"file":path.relative_to(root).as_posix(),"line":line_no,"evidence":"pattern_match_redacted"})
  for advisory in advisories or []:
   findings.append({"rule":"dependency_advisory","severity":advisory.get("severity","unknown"),"package":advisory.get("package"),"advisory_id":advisory.get("id"),"evidence":"provider_reported"})
  return {"findings":findings,"passed":not any(x["severity"] in {"critical","high"} for x in findings),"automatic_fix":False,"gate_version":"1.0"}
security_gate_service=SecurityGateService()
