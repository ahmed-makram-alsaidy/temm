import copy
import unittest

from sqlalchemy import delete, select

from core.ai_fleet.services.blueprint_approval import BlueprintApprovalService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AuditRecord, BlueprintProposalRecord, BlueprintProposalRevisionRecord, ProjectRecord, ProjectRequirementRecord, ProjectRequirementRevisionRecord


class BlueprintApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db(); self.project_id = f"blueprint-project-{id(self)}"; self.proposal_id = None; self.requirement_ids = []; self.service = BlueprintApprovalService()
        async with AsyncSessionLocal() as session: session.add(ProjectRecord(id=self.project_id, name="Blueprint", slug=f"blueprint-project-{id(self)}", project_type="software", owner="local")); await session.commit()
        self.content = {"template_id": "website-production", "template_version": "1.0", "approval_required": True, "implementation_started": False, "requirements": [{"title": "Accessible", "description": "Meet accessibility", "requirement_type": "quality", "priority": "must", "acceptance": [{"statement": "Audit passes"}]}], "questions": [{"text": "Target?"}]}
    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            if self.requirement_ids: await session.execute(delete(ProjectRequirementRevisionRecord).where(ProjectRequirementRevisionRecord.requirement_id.in_(self.requirement_ids))); await session.execute(delete(ProjectRequirementRecord).where(ProjectRequirementRecord.id.in_(self.requirement_ids)))
            if self.proposal_id: await session.execute(delete(BlueprintProposalRevisionRecord).where(BlueprintProposalRevisionRecord.proposal_id == self.proposal_id)); await session.execute(delete(BlueprintProposalRecord).where(BlueprintProposalRecord.id == self.proposal_id))
            await session.execute(delete(AuditRecord).where(AuditRecord.resource_id == self.project_id)); await session.execute(delete(ProjectRecord).where(ProjectRecord.id == self.project_id)); await session.commit()

    async def test_owner_edit_approval_materializes_proposed_requirements_and_freezes(self):
        async with AsyncSessionLocal() as session:
            proposal = await self.service.create(session, self.project_id, copy.deepcopy(self.content)); self.proposal_id = proposal.id
            edited_content = copy.deepcopy(self.content); edited_content["requirements"][0]["title"] = "Owner edited accessibility"
            edited = await self.service.edit(session, proposal.id, edited_content, 1)
            result = await self.service.approve(session, proposal.id, "owner", 2); self.requirement_ids = result["requirement_ids"]
            requirement = await session.get(ProjectRequirementRecord, self.requirement_ids[0])
            with self.assertRaises(Exception): await self.service.edit(session, proposal.id, edited_content, 3)
            revisions = (await session.execute(select(BlueprintProposalRevisionRecord).where(BlueprintProposalRevisionRecord.proposal_id == proposal.id))).scalars().all()
        self.assertEqual(requirement.title, "Owner edited accessibility"); self.assertEqual(requirement.status, "draft"); self.assertEqual(requirement.truth_state, "proposed"); self.assertTrue(result["owner_changes_retained"]); self.assertEqual(len(revisions), 3); self.assertEqual(result["proposal"]["status"], "approved")


if __name__ == "__main__": unittest.main()
