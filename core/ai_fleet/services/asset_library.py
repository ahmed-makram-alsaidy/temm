import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import (
    AssetCollectionMemberRecord,
    AssetCollectionProjectLinkRecord,
    AssetCollectionRecord,
    AssetRecord,
    ProjectRecord,
)


class AssetLibraryService:
    async def create(self, session: AsyncSession, name: str, owner: str, description: str = "") -> AssetCollectionRecord:
        if not name.strip() or not owner.strip():
            raise DomainError("validation_failed", message="Collection name and owner are required.")
        record = AssetCollectionRecord(
            id=f"collection-{uuid.uuid4().hex[:12]}",
            name=name.strip(),
            owner=owner.strip(),
            description=description.strip(),
        )
        session.add(record)
        await session.commit()
        return record

    async def list(self, session: AsyncSession, project_id: str | None = None) -> list[dict]:
        statement = select(AssetCollectionRecord)
        if project_id:
            statement = statement.join(
                AssetCollectionProjectLinkRecord,
                AssetCollectionProjectLinkRecord.collection_id == AssetCollectionRecord.id,
            ).where(AssetCollectionProjectLinkRecord.project_id == project_id)
        collections = (await session.execute(statement.order_by(AssetCollectionRecord.name, AssetCollectionRecord.id))).scalars().all()
        return [await self.detail(session, record.id) for record in collections]

    async def detail(self, session: AsyncSession, collection_id: str) -> dict:
        collection = await session.get(AssetCollectionRecord, collection_id)
        if not collection:
            raise DomainError("resource_not_found", message="Asset collection was not found.")
        memberships = (await session.execute(
            select(AssetCollectionMemberRecord)
            .where(AssetCollectionMemberRecord.collection_id == collection_id)
            .order_by(AssetCollectionMemberRecord.added_at, AssetCollectionMemberRecord.id)
        )).scalars().all()
        links = (await session.execute(
            select(AssetCollectionProjectLinkRecord)
            .where(AssetCollectionProjectLinkRecord.collection_id == collection_id)
            .order_by(AssetCollectionProjectLinkRecord.linked_at, AssetCollectionProjectLinkRecord.id)
        )).scalars().all()
        assets = []
        for membership in memberships:
            asset = await session.get(AssetRecord, membership.asset_id)
            assets.append({"membership": membership.to_dict(), "asset": asset.to_dict() if asset else None})
        return {**collection.to_dict(), "assets": assets, "project_links": [link.to_dict() for link in links]}

    async def add(self, session: AsyncSession, collection_id: str, asset_id: str) -> dict:
        collection = await session.get(AssetCollectionRecord, collection_id)
        asset = await session.get(AssetRecord, asset_id)
        if not collection or not asset:
            raise DomainError("resource_not_found", message="Collection or asset was not found.")
        membership = (await session.execute(
            select(AssetCollectionMemberRecord).where(
                AssetCollectionMemberRecord.collection_id == collection_id,
                AssetCollectionMemberRecord.asset_id == asset_id,
            )
        )).scalar_one_or_none()
        if not membership:
            membership = AssetCollectionMemberRecord(
                id=f"collection-member-{uuid.uuid4().hex[:12]}",
                collection_id=collection_id,
                asset_id=asset_id,
            )
            session.add(membership)
            await session.commit()
        return {
            "membership": membership.to_dict(),
            "asset": asset.to_dict(),
            "file_copied": False,
            "file_merged": False,
            "provenance_preserved": True,
        }

    async def link_project(self, session: AsyncSession, collection_id: str, project_id: str) -> dict:
        collection = await session.get(AssetCollectionRecord, collection_id)
        project = await session.get(ProjectRecord, project_id)
        if not collection or not project:
            raise DomainError("resource_not_found", message="Collection or project was not found.")
        link = (await session.execute(
            select(AssetCollectionProjectLinkRecord).where(
                AssetCollectionProjectLinkRecord.collection_id == collection_id,
                AssetCollectionProjectLinkRecord.project_id == project_id,
            )
        )).scalar_one_or_none()
        if not link:
            link = AssetCollectionProjectLinkRecord(
                id=f"collection-project-{uuid.uuid4().hex[:12]}",
                collection_id=collection_id,
                project_id=project_id,
            )
            session.add(link)
            await session.commit()
        return {**link.to_dict(), "file_copied": False, "file_merged": False}


asset_library_service = AssetLibraryService()
