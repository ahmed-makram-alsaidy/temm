import unittest
from core.ai_fleet.context import ContextSource, ContextSourceType

class ContextSourceContractTests(unittest.TestCase):
    def test_typed_sources_retain_identity_version_hash_and_provenance(self):
        file=ContextSource(ContextSourceType.FILE,"src/app.py","git:abc","observed","a"*64,"workspace-1","project-1").validate()
        requirement=ContextSource(ContextSourceType.REQUIREMENT,"req-1","3","owner_declared",project_id="project-1").validate()
        blueprint=ContextSource(ContextSourceType.BLUEPRINT,"bp-1","2","owner_declared",project_id="project-1").validate()
        need=ContextSource(ContextSourceType.NEED,"need-1","1","observed",project_id="project-1").validate()
        self.assertEqual(file.to_dict()["source_type"],"file"); self.assertEqual(file.content_hash,"a"*64); self.assertEqual(requirement.version,"3");self.assertEqual(blueprint.to_dict()["source_type"],"blueprint");self.assertEqual(need.to_dict()["source_type"],"need")
    def test_invalid_file_hash_and_unknown_type_fail(self):
        with self.assertRaises(ValueError): ContextSource(ContextSourceType.FILE,"x","1","observed",None,"w").validate()
        with self.assertRaises(ValueError): ContextSource(ContextSourceType.RUN,"run","1","bad").validate()

if __name__=="__main__": unittest.main()
