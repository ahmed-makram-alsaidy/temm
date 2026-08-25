import re
import uuid
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import ProjectRecord
from .audit import audit_service


PROJECT_TYPES = {"software", "website", "mobile_app", "business_system", "research", "content", "design", "other"}


class ProjectService:
    async def create(self, session: AsyncSession, values: Dict[str, Any]) -> ProjectRecord:
        raw_slug = values.get("slug") or values.get("name", "")
        if not values.get("slug"):
            raw_slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_slug).strip("-")
        slug = self._slug(raw_slug)
        project_type = values.get("project_type") or "software"
        if project_type not in PROJECT_TYPES or (await session.execute(select(ProjectRecord.id).where(ProjectRecord.slug == slug))).scalar_one_or_none():
            raise DomainError("resource_conflict" if await self._slug_exists(session, slug) else "validation_failed", message="Project slug already exists or type is invalid.")
        record = ProjectRecord(id=f"project-{uuid.uuid4().hex[:12]}", name=values["name"].strip(), slug=slug, purpose=values.get("purpose", "").strip(), project_type=project_type, owner=values.get("owner", "local_owner").strip(), lifecycle_status="active", revision=1)
        session.add(record)
        await audit_service.append(session, action="project.created", resource_type="project", resource_id=record.id, details={"actor": "local_system", "slug": slug, "revision": 1})
        await session.commit(); return record

    async def list(self, session: AsyncSession, include_archived: bool = False) -> List[ProjectRecord]:
        statement = select(ProjectRecord)
        if not include_archived: statement = statement.where(ProjectRecord.lifecycle_status == "active")
        return (await session.execute(statement.order_by(ProjectRecord.name, ProjectRecord.id))).scalars().all()

    async def update(self, session: AsyncSession, project_id: str, changes: Dict[str, Any], expected_revision: int) -> ProjectRecord:
        record = await self._get(session, project_id)
        if record.revision != expected_revision: raise DomainError("stale_revision", details={"current_revision": record.revision})
        if record.lifecycle_status != "active": raise DomainError("resource_conflict", message="Archived project cannot be edited.")
        if "slug" in changes:
            slug = self._slug(changes["slug"])
            if slug != record.slug and await self._slug_exists(session, slug): raise DomainError("resource_conflict", message="Project slug already exists.")
            record.slug = slug
        if "project_type" in changes and changes["project_type"] not in PROJECT_TYPES: raise DomainError("validation_failed", message="Project type is invalid.")
        for field in ["name", "purpose", "project_type", "owner"]:
            if field in changes: setattr(record, field, changes[field].strip() if isinstance(changes[field], str) else changes[field])
        record.revision += 1
        await audit_service.append(session, action="project.updated", resource_type="project", resource_id=record.id, details={"actor": "local_system", "fields": sorted(changes), "revision": record.revision})
        await session.commit(); return record

    async def transition(self, session: AsyncSession, project_id: str, target: str) -> ProjectRecord:
        record = await self._get(session, project_id)
        allowed = {("active", "archived"), ("archived", "active")}
        if (record.lifecycle_status, target) not in allowed: raise DomainError("resource_conflict", message="Project lifecycle transition is invalid.")
        record.lifecycle_status = target; record.revision += 1
        await audit_service.append(session, action=f"project.{target}", resource_type="project", resource_id=record.id, details={"actor": "local_system", "revision": record.revision, "history_preserved": True})
        await session.commit(); return record

    async def delete(self, session: AsyncSession, project_id: str) -> None:
        await self._get(session, project_id)
        raise DomainError("resource_conflict", message="Projects are archived, not hard-deleted, to preserve run and decision history.")

    async def _get(self, session: AsyncSession, project_id: str) -> ProjectRecord:
        record = await session.get(ProjectRecord, project_id)
        if not record: raise DomainError("resource_not_found", message="Project was not found.")
        return record

    async def _slug_exists(self, session: AsyncSession, slug: str) -> bool:
        return (await session.execute(select(ProjectRecord.id).where(ProjectRecord.slug == slug))).scalar_one_or_none() is not None

    def _slug(self, value: str) -> str:
        slug = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,127}", slug): raise DomainError("validation_failed", message="Project slug is invalid.")
        return slug


project_service = ProjectService()
