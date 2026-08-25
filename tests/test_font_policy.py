import unittest
from core.ai_fleet.services.font_policy import FontPolicyService
class FontPolicyTests(unittest.TestCase):
 def test_restricted_unknown_and_missing_tool_operations_blocked(self):
  service=FontPolicyService();self.assertTrue(service.authorize("metadata",{},[])["allowed"]);self.assertEqual(service.authorize("subset",{"approval_status":"pending","confidence":"unknown"},["fonttools"])["reason"],"license_not_approved");self.assertEqual(service.authorize("subset",{"approval_status":"approved","confidence":"verified","restrictions":["no_subset"]},["fonttools"])["reason"],"license_restriction");self.assertEqual(service.authorize("convert",{"approval_status":"approved","confidence":"high","restrictions":[]},[])["reason"],"tool_unavailable")
 def test_approved_operation_with_tool_allowed(self):self.assertTrue(FontPolicyService().authorize("subset",{"approval_status":"approved","confidence":"verified","restrictions":[]},["fonttools"])["allowed"])
if __name__=="__main__":unittest.main()
