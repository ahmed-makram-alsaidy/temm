from dataclasses import asdict,dataclass,field
from typing import Any,Dict,List,Optional
@dataclass(frozen=True)
class ValueMetric:
 metric_id:str;project_id:str;metric_type:str;value:Optional[str];unit:str;provenance:str;period_start:str;period_end:str;formula:Optional[str]=None;evidence:List[Dict[str,Any]]=field(default_factory=list);confidence:Optional[float]=None;assumptions:Dict[str,Any]=field(default_factory=dict)
 def validate(self):
  if not self.metric_id or not self.project_id or self.provenance not in {"measured","estimated","unknown"} or not self.unit or self.period_end<=self.period_start:raise ValueError("Value metric is invalid.")
  if self.provenance=="unknown" and self.value is not None:raise ValueError("Unknown value metric must be null.")
  if self.provenance=="measured" and (self.value is None or not self.evidence):raise ValueError("Measured value requires evidence.")
  if self.provenance=="estimated" and (self.value is None or not self.formula or not self.assumptions):raise ValueError("Estimated value requires formula and assumptions.")
  if self.confidence is not None and not 0<=self.confidence<=1:raise ValueError("Value confidence is invalid.")
  return self
 def to_dict(self):return asdict(self)
