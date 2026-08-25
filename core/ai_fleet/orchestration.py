from dataclasses import asdict,dataclass,field
from datetime import datetime
from decimal import Decimal
from typing import Any,Dict,List,Optional
@dataclass(frozen=True)
class OutcomeRequest:
 request_id:str;goal:str;project_id:Optional[str];owner_facts:Dict[str,Any];assumptions:Dict[str,Any];constraints:List[Dict[str,Any]];budget_amount:Optional[str];budget_currency:Optional[str];deadline:Optional[datetime];required_approvals:List[str];deliverables:List[Dict[str,Any]];created_by:str;version:str="1.0"
 def validate(self):
  if not self.request_id or not self.goal.strip() or not self.created_by or set(self.owner_facts)&set(self.assumptions):raise ValueError("Outcome request identity or fact classification is invalid.")
  if bool(self.budget_amount) != bool(self.budget_currency):raise ValueError("Budget amount and currency must be provided together.")
  if self.budget_amount is not None and (Decimal(self.budget_amount)<0 or len(self.budget_currency)!=3):raise ValueError("Outcome budget is invalid.")
  if not self.deliverables or any(not item.get("name") or not item.get("acceptance") for item in self.deliverables):raise ValueError("Outcome deliverables require names and acceptance criteria.")
  return self
 def to_dict(self):
  self.validate();payload=asdict(self);payload["deadline"]=self.deadline.isoformat() if self.deadline else None;return payload
