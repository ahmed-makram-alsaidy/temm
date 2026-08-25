import hashlib
import io
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import yaml
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from ..errors import DomainError
from ..plugin_catalog import CatalogError, CatalogSource, plugin_catalog
from ..plugin_package import PluginPackageError, contained_entrypoint, hash_plugin_folder
from ..plugin_permissions import plugin_permission_policy
from ..plugin_protocol import PluginManifest
from ..storage.models import PluginCatalogSourceRecord, PluginRecord
from ..url_safety import UrlSafetyPolicy, UrlSafetyService
from .approvals import approval_service
from .audit import audit_service


FetchJson = Callable[[str, UrlSafetyPolicy], Awaitable[dict[str, Any]]]
FetchBytes = Callable[[str, UrlSafetyPolicy], Awaitable[dict[str, Any]]]


class PluginMarketplaceService:
    def __init__(self, root: Path, safety: UrlSafetyService, fetch_json: FetchJson, fetch_bytes: FetchBytes):
        self.root = root
        self.safety = safety
        self.fetch_json = fetch_json
        self.fetch_bytes = fetch_bytes

    async def add_source(self, session, source_id: str, index_url: str, public_key: str) -> PluginCatalogSourceRecord:
        try:
            source = CatalogSource(source_id, index_url, public_key, False)
            self.safety.validate(index_url, UrlSafetyPolicy(max_bytes=2 * 1024 * 1024, allowed_content_types=("application/json",)))
        except (CatalogError, ValueError) as exc:
            raise DomainError("validation_failed", message=str(exc)) from exc
        if await session.get(PluginCatalogSourceRecord, source.source_id):
            raise DomainError("resource_conflict", message="Catalog source id is already registered.")
        record = PluginCatalogSourceRecord(id=source.source_id, index_url=source.index_url, public_key=source.public_key, enabled=False)
        session.add(record)
        await audit_service.append(session, action="plugin_catalog_source.added", resource_type="plugin_catalog_source", resource_id=record.id, details={"index_url": record.index_url})
        await session.commit()
        return record

    async def set_source_enabled(self, session, source_id: str, enabled: bool) -> PluginCatalogSourceRecord:
        record = await self._source(session, source_id)
        record.enabled = enabled
        if not enabled:
            record.catalog_json = "{}"
            record.last_state = "disabled"
            record.last_error = ""
            record.verified_at = None
            record.expires_at = None
        await audit_service.append(session, action="plugin_catalog_source.enabled" if enabled else "plugin_catalog_source.disabled", resource_type="plugin_catalog_source", resource_id=source_id)
        await session.commit()
        return record

    async def remove_source(self, session, source_id: str) -> None:
        record = await self._source(session, source_id)
        installed = (await session.execute(select(PluginRecord).where(PluginRecord.source_id == source_id))).scalars().first()
        if installed:
            raise DomainError("resource_conflict", message="Remove marketplace plugins from this source before deleting it.")
        await session.delete(record)
        await audit_service.append(session, action="plugin_catalog_source.removed", resource_type="plugin_catalog_source", resource_id=source_id)
        await session.commit()

    async def refresh(self, session, source_id: str, platform_name: str) -> dict[str, Any]:
        record = await self._source(session, source_id)
        source = CatalogSource(record.id, record.index_url, record.public_key, record.enabled)
        policy = UrlSafetyPolicy(max_bytes=2 * 1024 * 1024, allowed_content_types=("application/json",))
        try:
            self.safety.validate(record.index_url, policy)
            response = await self.fetch_json(record.index_url, policy)
            self.safety.validate_redirect_chain(response.get("redirect_chain", [record.index_url]), policy)
            self.safety.validate_response(response.get("content_type", ""), response.get("content_length"), policy)
            result = plugin_catalog.verify(source, response["json"], platform_name)
        except Exception as exc:
            record.last_state = "failed"
            record.last_error = str(exc)[:1000]
            record.catalog_json = "{}"
            await audit_service.append(session, action="plugin_catalog.refresh", resource_type="plugin_catalog_source", resource_id=source_id, outcome="failed", details={"error": record.last_error})
            await session.commit()
            if isinstance(exc, DomainError):
                raise
            raise DomainError("execution_unavailable", message="Catalog refresh failed verification.") from exc
        record.catalog_json = json.dumps(result, sort_keys=True)
        record.last_state = "verified"
        record.last_error = ""
        record.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record.expires_at = datetime.fromisoformat(result["expires_at"]).replace(tzinfo=None)
        await audit_service.append(session, action="plugin_catalog.refresh", resource_type="plugin_catalog_source", resource_id=source_id, details={"entries": len(result["entries"])})
        await session.commit()
        return result

    async def browse(self, session, source_id: str | None = None, content_type: str | None = None) -> list[dict[str, Any]]:
        statement = select(PluginCatalogSourceRecord).where(PluginCatalogSourceRecord.enabled.is_(True), PluginCatalogSourceRecord.last_state == "verified")
        if source_id:
            statement = statement.where(PluginCatalogSourceRecord.id == source_id)
        records = (await session.execute(statement.order_by(PluginCatalogSourceRecord.id))).scalars().all()
        now = datetime.utcnow()
        entries = []
        for record in records:
            if not record.expires_at or record.expires_at <= now:
                continue
            catalog = json.loads(record.catalog_json)
            for item in catalog.get("entries", []):
                if content_type and item.get("content_type", "plugin") != content_type:
                    continue
                entries.append({**item, "source_id": record.id, "catalog_expires_at": record.expires_at.isoformat()})
        return entries

    async def import_benchmark_pack(self, session, source_id: str, pack_id: str, version: str, approval_id: str):
        entries = await self.browse(session, source_id, "benchmark_pack")
        entry = next((item for item in entries if item["identity"] == {"id": pack_id, "version": version}), None)
        if not entry:
            raise DomainError("resource_not_found", message="Verified benchmark pack was not found or has expired.")
        await approval_service.consume(session, approval_id, "network", "benchmark_pack_import", f"{source_id}:{pack_id}:{version}")
        package = await self._download(entry["package"])
        try:
            text = package.decode("utf-8")
            payload = json.loads(text) if entry["package"]["media_type"] == "application/json" else yaml.safe_load(text)
        except (UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise DomainError("validation_failed", message="Benchmark pack could not be parsed.") from exc
        from .benchmark_packs import benchmark_pack_service
        record = await benchmark_pack_service.import_payload(session, payload, entry["package"]["url"], "marketplace")
        await audit_service.append(session, action="benchmark_pack_marketplace.imported", resource_type="benchmark_suite_version", resource_id=record.id, details={"source_id": source_id, "pack_id": pack_id, "version": version, "sha256": entry["package"]["sha256"]})
        await session.commit()
        return record

    async def import_workflow_template(self, session, source_id: str, template_id: str, version: str, approval_id: str):
        entries = await self.browse(session, source_id, "workflow_template")
        entry = next((item for item in entries if item["identity"] == {"id": template_id, "version": version}), None)
        if not entry:
            raise DomainError("resource_not_found", message="Verified workflow template was not found or has expired.")
        await approval_service.consume(session, approval_id, "network", "workflow_template_import", f"{source_id}:{template_id}:{version}")
        package = await self._download(entry["package"])
        try:
            text = package.decode("utf-8")
            payload = json.loads(text) if entry["package"]["media_type"] == "application/json" else yaml.safe_load(text)
        except (UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise DomainError("validation_failed", message="Workflow template could not be parsed.") from exc
        from .workflow_template_marketplace import workflow_template_marketplace_service
        record = await workflow_template_marketplace_service.import_payload(session, payload, entry["package"]["url"])
        await audit_service.append(session, action="workflow_template_marketplace.imported", resource_type="workflow_template_version", resource_id=record.id, details={"source_id": source_id, "template_id": template_id, "version": version, "sha256": entry["package"]["sha256"]})
        await session.commit()
        return record

    async def install(self, session, source_id: str, plugin_id: str, version: str, granted_permissions: list[str], permission_profile: str, approval_id: str) -> PluginRecord:
        entry = await self._entry(session, source_id, plugin_id, version)
        if not entry["compatible"] or not entry["platform_supported"]:
            raise DomainError("resource_conflict", message="Plugin version is not compatible with this installation.")
        manifest = PluginManifest.parse(entry["manifest"])
        try:
            plugin_permission_policy.enforce(manifest, permission_profile, granted_permissions)
        except (ValueError, PermissionError) as exc:
            raise DomainError("permission_denied", message=str(exc)) from exc
        scope_id = f"{source_id}:{plugin_id}:{version}"
        await approval_service.consume(session, approval_id, "network", "plugin_install", scope_id)
        package = await self._download(entry["package"])
        existing = await session.get(PluginRecord, plugin_id)
        if existing and existing.source_type != "marketplace":
            raise DomainError("resource_conflict", message="A local plugin already uses this id.")
        destination = self.root / plugin_id / version
        destination_created = False
        staged = self._extract(package, plugin_id)
        try:
            inspection = self._inspect(staged)
            if inspection["manifest"].to_dict() != manifest.to_dict() or inspection["folder_hash"] != entry["package"]["folder_sha256"]:
                raise DomainError("validation_failed", message="Downloaded plugin contents do not match signed catalog metadata.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(staged, destination)
            except FileExistsError as exc:
                raise DomainError("resource_conflict", message="This marketplace plugin version is already installed.") from exc
            destination_created = True
            previous_path = existing.path if existing else None
            previous_hash = existing.package_hash if existing else None
            if existing:
                existing.path = str(destination)
                existing.version = version
                existing.protocol_version = manifest.protocol
                existing.plugin_type = manifest.plugin_type.value
                existing.manifest = json.dumps(manifest.to_dict())
                existing.permissions = json.dumps(sorted(item.value for item in manifest.permissions))
                existing.granted_permissions = json.dumps(granted_permissions)
                existing.permission_profile = permission_profile
                existing.package_hash = inspection["folder_hash"]
                existing.entrypoint = str(destination / manifest.entrypoint)
                existing.load_state = "eligible"
                existing.previous_path = previous_path
                existing.previous_hash = previous_hash
                existing.source_package_url = entry["package"]["url"]
                existing.installed_at = datetime.utcnow()
                record = existing
            else:
                record = PluginRecord(id=plugin_id, name=manifest.name, path=str(destination), version=version, protocol_version=manifest.protocol, plugin_type=manifest.plugin_type.value, status="registered", manifest=json.dumps(manifest.to_dict()), permissions=json.dumps(sorted(item.value for item in manifest.permissions)), granted_permissions=json.dumps(granted_permissions), permission_profile=permission_profile, package_hash=inspection["folder_hash"], entrypoint=str(destination / manifest.entrypoint), load_state="eligible", source_type="marketplace", source_id=source_id, source_package_url=entry["package"]["url"], installed_at=datetime.utcnow())
                session.add(record)
            await audit_service.append(session, action="plugin_marketplace.updated" if existing else "plugin_marketplace.installed", resource_type="plugin", resource_id=plugin_id, details={"source_id": source_id, "version": version, "package_sha256": entry["package"]["sha256"]})
            await session.commit()
            return record
        except Exception:
            if destination_created and destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)

    async def rollback(self, session, plugin_id: str, approval_id: str) -> PluginRecord:
        record = await session.get(PluginRecord, plugin_id)
        if not record or record.source_type != "marketplace" or not record.previous_path or not record.previous_hash:
            raise DomainError("resource_conflict", message="No retained marketplace version is available for rollback.")
        await approval_service.consume(session, approval_id, "destructive", "plugin_rollback", plugin_id)
        previous = Path(record.previous_path)
        if not previous.is_dir() or self.root.resolve() not in previous.resolve().parents:
            raise DomainError("resource_conflict", message="Retained marketplace version is unavailable or unsafe.")
        inspection = self._inspect(previous)
        if inspection["folder_hash"] != record.previous_hash or inspection["manifest"].plugin_id != plugin_id:
            raise DomainError("validation_failed", message="Retained marketplace version failed integrity validation.")
        current_path, current_hash = record.path, record.package_hash
        manifest = inspection["manifest"]
        record.path = str(previous)
        record.version = manifest.version
        record.protocol_version = manifest.protocol
        record.plugin_type = manifest.plugin_type.value
        record.manifest = json.dumps(manifest.to_dict())
        record.permissions = json.dumps(sorted(item.value for item in manifest.permissions))
        record.package_hash = inspection["folder_hash"]
        record.entrypoint = str(previous / manifest.entrypoint)
        record.previous_path = current_path
        record.previous_hash = current_hash
        record.load_state = "eligible"
        await audit_service.append(session, action="plugin_marketplace.rolled_back", resource_type="plugin", resource_id=plugin_id, details={"version": manifest.version, "package_hash": inspection["folder_hash"]})
        await session.commit()
        return record

    async def remove(self, session, plugin_id: str, approval_id: str) -> None:
        record = await session.get(PluginRecord, plugin_id)
        if not record or record.source_type != "marketplace":
            raise DomainError("resource_not_found", message="Marketplace plugin was not found.")
        await approval_service.consume(session, approval_id, "destructive", "plugin_remove", plugin_id)
        path = Path(record.path)
        previous = Path(record.previous_path) if record.previous_path else None
        await session.delete(record)
        await audit_service.append(session, action="plugin_marketplace.removed", resource_type="plugin", resource_id=plugin_id, details={"version": record.version, "source_id": record.source_id})
        await session.commit()
        for managed in (path, previous):
            if managed and managed.is_dir() and self.root.resolve() in managed.resolve().parents:
                shutil.rmtree(managed, ignore_errors=True)

    async def _entry(self, session, source_id: str, plugin_id: str, version: str) -> dict[str, Any]:
        entries = await self.browse(session, source_id, "plugin")
        for entry in entries:
            if entry["manifest"]["id"] == plugin_id and entry["manifest"]["version"] == version:
                return entry
        raise DomainError("resource_not_found", message="Verified marketplace entry was not found or has expired.")

    async def _download(self, package: dict[str, Any]) -> bytes:
        allowed_media = package.get("media_type")
        policy = UrlSafetyPolicy(max_bytes=package["size"], allowed_content_types=(allowed_media,) if allowed_media else ("application/zip", "application/octet-stream"))
        self.safety.validate(package["url"], policy)
        response = await self.fetch_bytes(package["url"], policy)
        self.safety.validate_redirect_chain(response.get("redirect_chain", [package["url"]]), policy)
        data = response["content"]
        self.safety.validate_response(response.get("content_type", ""), len(data), policy)
        if len(data) != package["size"] or hashlib.sha256(data).hexdigest() != package["sha256"]:
            raise DomainError("validation_failed", message="Downloaded plugin package size or SHA-256 does not match the signed catalog.")
        return data

    def _extract(self, package: bytes, plugin_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=f".{plugin_id}-", dir=self.root))
        try:
            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                infos = archive.infolist()
                if not 1 <= len(infos) <= 1000:
                    raise DomainError("validation_failed", message="Plugin archive file count is invalid.")
                names = set()
                total = 0
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if "\\" in info.filename or info.flag_bits & 0x1 or path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] in {"", "."} or any(":" in part for part in path.parts):
                        raise DomainError("validation_failed", message="Plugin archive contains an unsafe path.")
                    normalized = path.as_posix().rstrip("/")
                    if normalized in names:
                        raise DomainError("validation_failed", message="Plugin archive contains duplicate paths.")
                    names.add(normalized)
                    mode = info.external_attr >> 16
                    file_type = mode & 0o170000
                    if file_type not in {0, 0o040000, 0o100000}:
                        raise DomainError("validation_failed", message="Plugin archive special files are not allowed.")
                    total += info.file_size
                    if info.file_size > 10 * 1024 * 1024 or total > 100 * 1024 * 1024:
                        raise DomainError("validation_failed", message="Plugin archive exceeds extraction limits.")
                archive.extractall(staged)
            return staged
        except Exception:
            shutil.rmtree(staged, ignore_errors=True)
            raise

    def _inspect(self, folder: Path) -> dict[str, Any]:
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            raise DomainError("validation_failed", message="Plugin archive is missing manifest.json at its root.")
        try:
            manifest = PluginManifest.parse(json.loads(manifest_path.read_text(encoding="utf-8")))
            contained_entrypoint(folder, manifest.entrypoint)
            folder_hash = hash_plugin_folder(folder)
        except (ValueError, OSError, PluginPackageError, json.JSONDecodeError) as exc:
            raise DomainError("validation_failed", message="Plugin archive manifest or contents are invalid.") from exc
        return {"manifest": manifest, "folder_hash": folder_hash}

    async def _source(self, session, source_id: str) -> PluginCatalogSourceRecord:
        record = await session.get(PluginCatalogSourceRecord, source_id)
        if not record:
            raise DomainError("resource_not_found", message="Plugin catalog source was not found.")
        return record
