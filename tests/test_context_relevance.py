import unittest
from core.ai_fleet.context import ContextSource, ContextSourceType
from core.ai_fleet.services.context_relevance import ContextRelevanceService

class ContextRelevanceTests(unittest.TestCase):
    def test_selection_reasons_and_exclusions_are_deterministic(self):
        sources=[ContextSource(ContextSourceType.FILE,"file","1","observed","a"*64,"w","p"),ContextSource(ContextSourceType.REQUIREMENT,"req-direct","1","owner_declared",project_id="p"),ContextSource(ContextSourceType.REQUIREMENT,"req-impact","1","owner_declared",project_id="p"),ContextSource(ContextSourceType.DECISION,"decision","1","owner_declared",project_id="p",metadata={"status":"approved","scope_type":"component","scope_id":"billing"}),ContextSource(ContextSourceType.RESEARCH,"research","1","observed",project_id="p")]
        task={"project_id":"p","component":"billing","source_ids":["file"],"requirement_ids":["req-direct"]}
        first=ContextRelevanceService().select(sources,task,["req-impact"]); second=ContextRelevanceService().select(list(reversed(sources)),task,["req-impact"])
        self.assertEqual(first,second); self.assertEqual([item["reason"] for item in first["selected"]],["explicit_source","linked_requirement","requirement_impact","active_decision_scope"]); self.assertEqual(first["excluded"],[{"source_type":"research","source_id":"research","reason":"no_explicit_graph_relevance"}])

if __name__=="__main__": unittest.main()
