import unittest
from core.ai_fleet.workflow_nodes import NODE_CONTRACTS,build_node
class NodeContractTests(unittest.TestCase):
 def test_all_canonical_node_types_are_typed_and_capability_based(self):
  self.assertEqual(set(NODE_CONTRACTS),{"task","classify","router","agent","judge","critic","gate","approval","output"})
  for kind in NODE_CONTRACTS:
   node=build_node(kind,kind);self.assertTrue(node.inputs or kind=="task");self.assertTrue(node.outputs)
  self.assertIn("quality_gate",build_node("g","gate").required_capabilities)
 def test_unknown_type_fails(self):
  with self.assertRaises(ValueError):build_node("x","magic")
if __name__=="__main__":unittest.main()
