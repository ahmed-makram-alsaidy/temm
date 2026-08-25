import unittest
from core.ai_fleet.research import ResearchCapability,ResearchConnector,ResearchConnectorPolicy
class Connector(ResearchConnector):
 connector_id="fixture"; capabilities=frozenset(ResearchCapability); policy=ResearchConnectorPolicy("approval_required",60)
 async def search(self,q): return []
 async def fetch(self,u): return {}
 async def parse(self,d): return d
 async def cite(self,d,e): return {"excerpt":e}
class ResearchConnectorTests(unittest.TestCase):
 def test_brand_neutral_capability_and_policy_contract(self):
  connector=Connector().validate(); self.assertEqual(connector.protocol_version,"1.0"); self.assertEqual(connector.policy.network_permission,"approval_required"); self.assertEqual(set(connector.capabilities),set(ResearchCapability))
 def test_fetch_without_network_and_invalid_limits_fail(self):
  class Offline(Connector): policy=ResearchConnectorPolicy("none",1)
  with self.assertRaises(ValueError): Offline().validate()
  with self.assertRaises(ValueError): ResearchConnectorPolicy("allowed",0).validate()
if __name__=="__main__": unittest.main()
