import unittest
from datetime import datetime
from core.ai_fleet.services.package_research import PackageResearchService
class PackageResearchTests(unittest.TestCase):
 def test_complete_current_evidence_is_citation_ready(self):
  at=datetime(2026,1,1);result=PackageResearchService().assess("pkg",{"source_url":"https://registry.example/pkg","latest_version":"2.0","license":"MIT"},{"source_url":"https://docs.example/pkg","content_hash":"a"*64},{"source_url":"https://security.example/pkg","advisories":[]},at)
  self.assertTrue(result["recommendation_available"]);self.assertEqual(result["as_of"],at.isoformat());self.assertEqual({x["kind"] for x in result["evidence"]},{"registry","documentation","security"})
 def test_missing_license_or_security_prevents_recommendation(self):
  result=PackageResearchService().assess("pkg",{"source_url":"https://r","latest_version":"1","license":None},{"source_url":"https://d"},{"source_url":"https://s","advisories":None},datetime(2026,1,1));self.assertFalse(result["recommendation_available"]);self.assertEqual(result["missing_evidence"],["license","security_advisories"])
if __name__=="__main__":unittest.main()
