from dataclasses import asdict,dataclass,field
from typing import Any,Dict,List,Optional
from .domain import CAPABILITIES
@dataclass(frozen=True)
class QualityGate:
 gate_id:str;version:str;required_capabilities:List[str];inputs:List[str];applicability:Dict[str,Any];checks:List[Dict[str,Any]];severity:str;max_retries:int;waivable:bool
 def validate(self):
  if not self.gate_id or not self.version or set(self.required_capabilities)-set(CAPABILITIES) or not self.checks or self.severity not in {"info","low","medium","high","critical"} or not 0<=self.max_retries<=10:raise ValueError("Quality gate is invalid.")
  return self
@dataclass(frozen=True)
class QualityGateResult:
 gate_id:str;gate_version:str;applicable:bool;status:str;evidence:List[Dict[str,Any]];attempt:int;waiver:Optional[Dict[str,Any]]=None
 def validate(self,gate:QualityGate):
  gate.validate()
  if self.gate_id!=gate.gate_id or self.gate_version!=gate.version or self.status not in {"passed","failed","skipped","waived"} or self.attempt<1 or self.attempt>gate.max_retries+1:raise ValueError("Quality gate result is invalid.")
  if self.status=="passed" and not self.evidence:raise ValueError("Passed quality gate requires evidence.")
  if self.status=="waived" and (not gate.waivable or not self.waiver or not self.waiver.get("actor") or not self.waiver.get("rationale")):raise ValueError("Quality gate waiver is invalid.")
  return self
 def to_dict(self):return asdict(self)
