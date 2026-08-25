import unittest
from core.ai_fleet.services.readiness_report import ReadinessReportService
class ReadinessReportTests(unittest.TestCase):
 def deliverable(self):return {"id":"d","version":"1","requirement_ids":["r"],"asset_ids":["a"],"run_ids":["run"],"gate_ids":["g"]}
 def test_unknown_or_failed_evidence_prevents_success_claim(self):
  report=ReadinessReportService().generate(self.deliverable(),{"ready":True},[{"id":"x","status":"unknown"}]);self.assertFalse(report["ready"]);self.assertFalse(report["deployment_ready"]);self.assertFalse(report["success_claim"]);self.assertIn("not established",report["statement"])
 def test_ready_report_retains_waivers_and_trace(self):
  report=ReadinessReportService().generate(self.deliverable(),{"ready":True,"blocking_findings":[]},[{"id":"x","status":"passed","evidence":{}},{"id":"w","status":"waived","waiver":{"actor":"owner"}}]);self.assertTrue(report["ready"]);self.assertEqual(report["sections"]["waived"][0]["id"],"w");self.assertEqual(report["trace"]["run_ids"],["run"])
if __name__=="__main__":unittest.main()
