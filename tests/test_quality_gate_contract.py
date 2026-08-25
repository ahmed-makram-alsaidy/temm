import unittest
from core.ai_fleet.quality import QualityGate,QualityGateResult
class QualityGateTests(unittest.TestCase):
 def gate(self):return QualityGate("tests","1.0",["shell"],["workspace"],{"project_type":"software"},[{"type":"command","id":"unit"}],"high",2,True)
 def test_versioned_capability_contract_and_evidence(self):
  gate=self.gate().validate();result=QualityGateResult("tests","1.0",True,"passed",[{"run_id":"run-1","exit_code":0}],1).validate(gate);self.assertEqual(result.to_dict()["gate_version"],"1.0")
 def test_unknown_capability_pass_without_evidence_and_bad_waiver_fail(self):
  with self.assertRaises(ValueError):QualityGate("x","1",["magic"],[],[{}],[{}],"high",0,False).validate()
  with self.assertRaises(ValueError):QualityGateResult("tests","1.0",True,"passed",[],1).validate(self.gate())
  with self.assertRaises(ValueError):QualityGateResult("tests","1.0",True,"waived",[],1,{"actor":"owner"}).validate(self.gate())
if __name__=="__main__":unittest.main()
