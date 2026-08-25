import unittest
from core.ai_fleet.completeness import RULES,rules_for
class CompletenessCatalogTests(unittest.TestCase):
 def test_catalog_covers_canonical_rules_and_is_versioned(self):
  ids={r.rule_id for r in RULES};self.assertEqual(ids,{"todo_markers","placeholder_content","missing_assets","missing_fonts","broken_imports","broken_links","favicon","metadata","tests","build","accessibility","performance","blockers"});self.assertTrue(all(r.version and r.validate() for r in RULES))
 def test_project_type_applicability(self):
  website={r["rule_id"] for r in rules_for("website")};research={r["rule_id"] for r in rules_for("research")};self.assertIn("seo" if False else "favicon",website);self.assertNotIn("favicon",research);self.assertIn("blockers",research)
if __name__=="__main__":unittest.main()
