import unittest
from core.ai_fleet.services.context_budget import ContextBudgetService

class ContextBudgetTests(unittest.TestCase):
    def test_measured_overrides_estimate_and_priority_is_deterministic(self):
        items=[{"source_id":"b","priority":2,"estimated_tokens":100,"estimation_method":"chars/4"},{"source_id":"a","priority":1,"measured_tokens":80,"estimated_tokens":999}]
        result=ContextBudgetService().budget(items,200,20,"truncate")
        self.assertEqual([x["source_id"] for x in result["selected"]],["a","b"]); self.assertEqual(result["selected"][0]["token_provenance"],"measured"); self.assertEqual(result["used_tokens"],180)
    def test_fail_and_truncate_record_evidence(self):
        items=[{"source_id":"a","priority":1,"measured_tokens":80},{"source_id":"b","priority":2,"measured_tokens":80}]
        with self.assertRaises(Exception): ContextBudgetService().budget(items,100,0,"fail")
        result=ContextBudgetService().budget(items,100,0,"truncate"); self.assertTrue(result["truncated"]); self.assertEqual(result["excluded"][0]["reason"],"token_budget_exceeded"); self.assertEqual(result["remaining_tokens"],20)
    def test_truncation_keeps_the_highest_priority_sources_and_never_vetoes(self):
        """Over-budget is a thinner pack, not a refusal: production evidence
        2026-08-20 has a fixed pack budget aborting every repair dispatch before its
        executor launched, over sources the executor is never handed anyway."""
        items=[{"source_id":"keep","priority":1,"measured_tokens":40},{"source_id":"drop","priority":2,"measured_tokens":400}]
        result=ContextBudgetService().budget(items,100,20,"truncate")
        self.assertEqual([x["source_id"] for x in result["selected"]],["keep"]); self.assertEqual([x["source_id"] for x in result["excluded"]],["drop"]); self.assertEqual(result["available_tokens"],80)
    def test_a_budget_that_admits_no_source_is_rejected_rather_than_reported_empty(self):
        """Truncation degrades a pack; it cannot manufacture one."""
        with self.assertRaisesRegex(Exception,"admits no source"): ContextBudgetService().budget([{"source_id":"a","measured_tokens":50}],10,0,"truncate")
        self.assertEqual(ContextBudgetService().budget([],10,0,"truncate")["selected"],[])
    def test_estimate_without_method_and_invalid_reserve_fail(self):
        with self.assertRaises(Exception): ContextBudgetService().budget([{"source_id":"a","estimated_tokens":1}],10)
        with self.assertRaises(Exception): ContextBudgetService().budget([],10,10)

if __name__=="__main__": unittest.main()
