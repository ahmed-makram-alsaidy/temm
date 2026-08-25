import unittest
from core.ai_fleet.services.research_planner import ResearchPlannerService
class ResearchPlannerTests(unittest.TestCase):
 def test_needs_become_bounded_queries_and_sensitive_actions_require_approval(self):
  needs=[{"id":"n1","state":"open","need_type":"information","title":"Version","description":"What is current?","source_policy":{"network":True,"paid":True,"private":True,"max_sources":100}}]
  result=ResearchPlannerService().plan(needs);q=result["queries"][0];self.assertEqual(q["query_kind"],"factual_retrieval");self.assertEqual(q["max_sources"],20);self.assertEqual(q["approval_required"],["network","paid","private"]);self.assertEqual(q["status"],"blocked_approval")
  allowed=ResearchPlannerService().plan(needs,True,True,True)["queries"][0];self.assertEqual(allowed["status"],"planned")
if __name__=="__main__":unittest.main()
