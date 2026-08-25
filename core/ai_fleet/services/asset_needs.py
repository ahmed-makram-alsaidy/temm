import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import AssetRecord, AssetUsageRecord, ProjectNeedRecord, WorkspaceRecord


class AssetNeedService:
    async def derive(self, session: AsyncSession, project_id: str) -> list[ProjectNeedRecord]:
        assets = (await session.execute(select(AssetRecord).where(AssetRecord.project_id == project_id))).scalars().all()
        created = []
        for asset in assets:
            usages = (await session.execute(select(AssetUsageRecord).where(AssetUsageRecord.asset_id == asset.id, AssetUsageRecord.required.is_(True)))).scalars().all()
            if not usages:
                continue
            workspace = await session.get(WorkspaceRecord, asset.workspace_id)
            exists = bool(workspace and (Path(workspace.path) / asset.relative_path).is_file())
            if exists and asset.state == "ready":
                continue
            dedupe_key = f"asset:{asset.id}:required"
            need = (await session.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == project_id, ProjectNeedRecord.dedupe_key == dedupe_key))).scalar_one_or_none()
            if need:
                created.append(need)
                continue
            blocked_nodes = sorted({usage.target_id for usage in usages})
            roles = sorted({usage.usage_role for usage in usages})
            constraints = {"asset_type": asset.asset_type, "mime_type": asset.mime_type, "usage_roles": roles, "license_policy": "approved_license_required", "recorded_state": asset.state, "file_exists": exists}
            need = ProjectNeedRecord(
                id=f"need-{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                need_type="asset",
                title=f"Resolve required asset: {asset.relative_path}",
                description=json.dumps(constraints, sort_keys=True),
                source_type="asset_usage",
                source_id=asset.id,
                impact="blocking",
                blocked_nodes_json=json.dumps(blocked_nodes),
                state="open",
                dedupe_key=dedupe_key,
            )
            session.add(need)
            created.append(need)
        await session.commit()
        return created


asset_need_service = AssetNeedService()
