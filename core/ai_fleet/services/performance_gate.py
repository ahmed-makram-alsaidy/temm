from pathlib import Path
from typing import Any,Dict
class PerformanceGateService:
 def assess(self,build_path:Path,size_budget_bytes:int|None,runtime:Dict[str,Any]|None,environment:Dict[str,Any]):
  size=None
  if build_path.exists():size=sum(path.stat().st_size for path in build_path.rglob("*") if path.is_file()) if build_path.is_dir() else build_path.stat().st_size
  findings=[]
  if size_budget_bytes is not None and size is not None and size>size_budget_bytes:findings.append({"rule":"build_size_budget","severity":"high","measured_bytes":size,"budget_bytes":size_budget_bytes})
  metrics={"build_size_bytes":{"value":size,"provenance":"measured" if size is not None else "unknown","method":"filesystem_sum" if size is not None else None}}
  for name in ["ttft_ms","duration_ms","tokens_per_second"]:
   item=(runtime or {}).get(name)
   metrics[name]=item if item else {"value":None,"provenance":"unknown","method":None}
  return {"passed":not findings,"findings":findings,"metrics":metrics,"environment":environment,"gate_version":"1.0"}
performance_gate_service=PerformanceGateService()
