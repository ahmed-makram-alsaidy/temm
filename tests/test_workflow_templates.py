import unittest
from core.ai_fleet.workflow_templates import TEMPLATES
class WorkflowTemplateTests(unittest.TestCase):
 def test_required_templates_conform_and_declare_prerequisites_gates(self):
  self.assertEqual(set(TEMPLATES),{"code-review","feature","bug","security","research","compare","benchmark"})
  for template in TEMPLATES.values():
   template.validate();self.assertTrue(template.prerequisites);self.assertTrue(template.gate_ids);self.assertEqual(template.definition.version,"1.0")
 def test_templates_do_not_claim_unconditional_execution(self):
  for template in TEMPLATES.values():self.assertNotIn("executable",template.__dict__)
if __name__=="__main__":unittest.main()
