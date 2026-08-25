import unittest
from core.ai_fleet.services.seo_gate import SeoContentGateService
class SeoGateTests(unittest.TestCase):
 def test_website_fixture_reports_metadata_files_links_and_placeholders(self):
  result=SeoContentGateService().assess("website","<html><body>TODO</body></html>",set(),[{"url":"/missing","status":404}]);rules={x["rule"] for x in result["findings"]};self.assertTrue({"title_missing","description_missing","canonical_missing","sitemap.xml_missing","robots.txt_missing","placeholder_content","broken_link"}<=rules);self.assertFalse(result["passed"])
 def test_non_website_is_not_applicable(self):
  result=SeoContentGateService().assess("software","",set());self.assertFalse(result["applicable"]);self.assertTrue(result["passed"])
if __name__=="__main__":unittest.main()
