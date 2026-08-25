import unittest

from core.ai_fleet.services.production_path_certification import ProductionPathCertificationService


class ProductionPathCertificationTests(unittest.TestCase):
    def test_service_uses_normal_dispatcher_contract(self):
        service = ProductionPathCertificationService()
        self.assertTrue(hasattr(service, "certify"))


if __name__ == "__main__":
    unittest.main()
