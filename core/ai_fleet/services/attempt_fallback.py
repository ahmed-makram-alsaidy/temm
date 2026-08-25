from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from ..errors import DomainError
from .fallback import FallbackService
class AttemptFallbackService:
 async def execute(self,session:AsyncSession,run_id,routes,executor,max_attempts,max_spend):
  if not 1<=max_attempts<=20 or Decimal(max_spend)<0:raise DomainError("validation_failed",message="Fallback constraints are invalid.")
  selected=[];reserved=Decimal("0");stop=None
  for route in routes:
   if len(selected)>=max_attempts:stop="max_attempts";break
   estimate=route.get("estimated_cost")
   if estimate is None:stop="cost_unknown";break
   if reserved+Decimal(str(estimate))>Decimal(max_spend):stop="max_spend";break
   reserved+=Decimal(str(estimate));selected.append(route)
  if not selected:raise DomainError("resource_conflict",message="No fallback route fits task constraints.",details={"stop_reason":stop})
  result=await FallbackService().execute(session,run_id,selected,executor);result.update({"constraint_stop_reason":stop,"reserved_spend":str(reserved),"max_attempts":max_attempts,"max_spend":str(Decimal(max_spend))});return result
attempt_fallback_service=AttemptFallbackService()
