import unittest
from datetime import datetime
from core.ai_fleet.orchestration import OutcomeRequest
class OutcomeRequestTests(unittest.TestCase):
 def valid(self):return OutcomeRequest("outcome-1","Build clinic CRM","project-1",{"region":"EG"},{"users":100},[{"type":"privacy","value":"local-first"}],"100","USD",datetime(2026,12,1),["spend"],[{"name":"application","acceptance":["tests pass"]}],"owner")
 def test_owner_facts_and_assumptions_are_separate(self):
  payload=self.valid().to_dict();self.assertEqual(payload["owner_facts"],{"region":"EG"});self.assertEqual(payload["assumptions"],{"users":100});self.assertEqual(payload["budget_currency"],"USD")
 def test_overlap_invalid_budget_and_missing_acceptance_fail(self):
  value=self.valid()
  with self.assertRaises(ValueError):OutcomeRequest(**{**value.__dict__,"assumptions":{"region":"unknown"}}).validate()
  with self.assertRaises(ValueError):OutcomeRequest(**{**value.__dict__,"budget_currency":None}).validate()
  with self.assertRaises(ValueError):OutcomeRequest(**{**value.__dict__,"deliverables":[{"name":"app"}]}).validate()
if __name__=="__main__":unittest.main()
