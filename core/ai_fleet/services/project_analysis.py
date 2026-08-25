from typing import Any,Dict,List
from ..blueprints import BlueprintTemplate
from ..orchestration import OutcomeRequest
class ProjectAnalysisService:
 def analyze(self,request:OutcomeRequest,template:BlueprintTemplate,brain_facts:List[Dict[str,Any]]):
  request.validate();template.validate();confirmed={**request.owner_facts}
  for fact in brain_facts:
   if fact.get("truth_state")=="confirmed":confirmed[fact.get("fact_key")]=fact.get("value")
  questions=[]
  for section in template.sections:
   for question in section.questions:
    if question.required and question.question_id not in confirmed:questions.append({"question_id":question.question_id,"section_id":section.section_id,"text":question.text,"blocking":True,"reason":"required_owner_fact_missing"})
  proposals=[{"section_id":section.section_id,"status":"proposed","requirement_types":section.requirement_types} for section in template.sections]
  return {"request_id":request.request_id,"questions":questions,"proposals":proposals,"blocking_clarifications":len(questions),"implementation_allowed":False if questions else False,"implementation_started":False,"assumptions":request.assumptions,"confirmed_fact_keys":sorted(confirmed),"analysis_version":"1.0"}
project_analysis_service=ProjectAnalysisService()
