from decimal import Decimal,ROUND_HALF_UP
from typing import Dict,List
class ReworkValueService:
 def calculate(self,findings:List[Dict],assumptions:Dict):
  caught=[x for x in findings if x.get("status") in {"resolved","waived","open"} and x.get("evidence")]
  hours=Decimal(str(assumptions.get("hours_per_defect",0)));rate=Decimal(str(assumptions.get("hourly_value",0)))
  if hours<0 or rate<0:raise ValueError("Rework assumptions cannot be negative.")
  estimated=(Decimal(len(caught))*hours*rate).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
  return {"defects_caught":{"value":len(caught),"provenance":"measured","evidence_ids":[x.get("id") for x in caught]},"estimated_rework_prevented":{"value":str(estimated),"unit":"currency","provenance":"estimated","formula":"defects_caught*hours_per_defect*hourly_value","assumptions":{"hours_per_defect":str(hours),"hourly_value":str(rate)}}}
rework_value_service=ReworkValueService()
