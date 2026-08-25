import unittest
from core.ai_fleet.blueprints import BlueprintQuestion,BlueprintSection,BlueprintTemplate
from core.ai_fleet.orchestration import OutcomeRequest
from core.ai_fleet.services.project_analysis import ProjectAnalysisService
class ProjectAnalysisTests(unittest.TestCase):
 def test_assumptions_do_not_satisfy_required_owner_facts(self):
  request=OutcomeRequest("r","goal","p",{}, {"owner":"assumed"},[],None,None,None,[],[{"name":"app","acceptance":["done"]}],"owner")
  template=BlueprintTemplate("t","1","software",["coding"],[BlueprintSection("s","S",["functional"],questions=[BlueprintQuestion("owner","Who owns it?","text",True)])])
  result=ProjectAnalysisService().analyze(request,template,[]);self.assertEqual(result["blocking_clarifications"],1);self.assertFalse(result["implementation_allowed"]);self.assertFalse(result["implementation_started"]);self.assertEqual(result["proposals"][0]["status"],"proposed")
 def test_confirmed_brain_fact_resolves_question_but_does_not_start_work(self):
  request=OutcomeRequest("r","goal","p",{}, {},[],None,None,None,[],[{"name":"app","acceptance":["done"]}],"owner");template=BlueprintTemplate("t","1","software",["coding"],[BlueprintSection("s","S",["functional"],questions=[BlueprintQuestion("owner","Who?","text",True)])]);result=ProjectAnalysisService().analyze(request,template,[{"fact_key":"owner","value":"Alice","truth_state":"confirmed"}]);self.assertEqual(result["questions"],[]);self.assertFalse(result["implementation_started"])
if __name__=="__main__":unittest.main()
