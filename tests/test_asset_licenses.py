import unittest
from sqlalchemy import delete
from core.ai_fleet.storage.database import AsyncSessionLocal,init_db
from core.ai_fleet.storage.models import AssetLicenseRecord
class AssetLicenseTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):await init_db();self.ids=[f"license-{id(self)}-{i}" for i in range(2)]
 async def asyncTearDown(self):
  async with AsyncSessionLocal() as s:await s.execute(delete(AssetLicenseRecord).where(AssetLicenseRecord.id.in_(self.ids)));await s.commit()
 async def test_unknown_never_commercially_safe_and_approved_verified_can_be(self):
  unknown=AssetLicenseRecord(id=self.ids[0],name="Unknown",confidence="unknown",approval_status="pending",restrictions_json="[]");approved=AssetLicenseRecord(id=self.ids[1],name="Owned",source_uri="https://example.com/license",confidence="verified",approval_status="approved",approved_by="owner",restrictions_json='["attribution"]')
  async with AsyncSessionLocal() as s:s.add_all([unknown,approved]);await s.commit()
  self.assertFalse(unknown.to_dict()["commercially_safe"]);self.assertTrue(approved.to_dict()["commercially_safe"]);self.assertEqual(approved.to_dict()["restrictions"],["attribution"])
if __name__=="__main__":unittest.main()
