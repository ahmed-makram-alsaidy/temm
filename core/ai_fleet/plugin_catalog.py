import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .plugin_protocol import PluginManifest, negotiate_protocol


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogSource:
    source_id: str
    index_url: str
    public_key: str
    enabled: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", self.source_id):
            raise CatalogError("Catalog source id is invalid.")
        parsed = urlparse(self.index_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise CatalogError("Catalog source URL must be an HTTPS URL without credentials or fragments.")
        try:
            key = base64.b64decode(self.public_key, validate=True)
        except ValueError as exc:
            raise CatalogError("Catalog public key is invalid.") from exc
        if len(key) != 32:
            raise CatalogError("Catalog public key must be an Ed25519 key.")


class PluginCatalog:
    def canonical_payload(self, catalog: dict[str, Any]) -> bytes:
        payload = {key: value for key, value in catalog.items() if key != "signature"}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def verify(self, source: CatalogSource, catalog: dict[str, Any], platform_name: str) -> dict[str, Any]:
        if not source.enabled:
            raise CatalogError("Catalog source is not enabled.")
        if catalog.get("source_id") != source.source_id or catalog.get("schema_version") != "1.0":
            raise CatalogError("Catalog identity or schema version is invalid.")
        signature = catalog.get("signature")
        if not isinstance(signature, str):
            raise CatalogError("Catalog signature is missing.")
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(source.public_key, validate=True)).verify(
                base64.b64decode(signature, validate=True), self.canonical_payload(catalog)
            )
        except (ValueError, InvalidSignature) as exc:
            raise CatalogError("Catalog signature verification failed.") from exc
        generated_at = self._timestamp(catalog.get("generated_at"), "generated_at")
        expires_at = self._timestamp(catalog.get("expires_at"), "expires_at")
        if expires_at <= generated_at or expires_at <= datetime.now(timezone.utc):
            raise CatalogError("Catalog is expired or has an invalid validity period.")
        entries = catalog.get("entries")
        if not isinstance(entries, list) or len(entries) > 10000:
            raise CatalogError("Catalog entries are invalid.")
        normalized = [self._entry(item, platform_name) for item in entries]
        identities = [(item["content_type"], item["identity"]["id"], item["identity"]["version"]) for item in normalized]
        if len(identities) != len(set(identities)):
            raise CatalogError("Catalog contains duplicate plugin versions.")
        return {
            "source_id": source.source_id,
            "verified": True,
            "generated_at": generated_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "entries": normalized,
            "automatic_trust": False,
            "installation_enabled": False,
        }

    def _entry(self, value: Any, platform_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CatalogError("Catalog entry is invalid.")
        content_type = str(value.get("content_type") or "plugin")
        if content_type == "benchmark_pack":
            return self._benchmark_entry(value)
        if content_type == "workflow_template":
            return self._workflow_entry(value)
        if content_type != "plugin":
            raise CatalogError("Catalog content type is invalid.")
        manifest = PluginManifest.parse(value.get("manifest") or {})
        package = value.get("package")
        if not isinstance(package, dict):
            raise CatalogError("Catalog package metadata is invalid.")
        package_url = str(package.get("url") or "")
        parsed = urlparse(package_url)
        digest = str(package.get("sha256") or "")
        folder_digest = str(package.get("folder_sha256") or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise CatalogError("Plugin package URL must be an HTTPS URL without credentials or fragments.")
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or not re.fullmatch(r"[a-f0-9]{64}", folder_digest):
            raise CatalogError("Plugin package SHA-256 is invalid.")
        author = value.get("author")
        source_code_url = str(value.get("source_code_url") or "")
        source_parsed = urlparse(source_code_url)
        if not isinstance(author, str) or not author.strip() or len(author) > 160:
            raise CatalogError("Plugin author is invalid.")
        if source_parsed.scheme != "https" or not source_parsed.hostname:
            raise CatalogError("Plugin source code URL is invalid.")
        return {
            "content_type": "plugin",
            "identity": {"id": manifest.plugin_id, "version": manifest.version},
            "manifest": manifest.to_dict(),
            "author": author.strip(),
            "source_code_url": source_code_url,
            "package": {"url": package_url, "sha256": digest, "folder_sha256": folder_digest, "size": self._size(package.get("size"))},
            "compatible": negotiate_protocol(manifest.protocol),
            "platform_supported": platform_name in manifest.platforms,
            "permissions": sorted(item.value for item in manifest.permissions),
            "reputation": "unverified",
            "requires_permission_review": True,
            "rollback": {"retain_previous_package": True, "previous_hash_required": True},
        }

    def _benchmark_entry(self, value: dict[str, Any]) -> dict[str, Any]:
        pack = value.get("pack")
        package = value.get("package")
        if not isinstance(pack, dict) or not isinstance(package, dict):
            raise CatalogError("Benchmark pack metadata is invalid.")
        pack_id = str(pack.get("id") or "")
        version = str(pack.get("version") or "")
        schema_version = str(pack.get("schema_version") or "")
        category = str(pack.get("category") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", pack_id) or not re.fullmatch(r"\d+\.\d+\.\d+", version) or schema_version != "1.0" or not category or len(category) > 64:
            raise CatalogError("Benchmark pack identity or compatibility is invalid.")
        package_url = str(package.get("url") or "")
        parsed = urlparse(package_url)
        digest = str(package.get("sha256") or "")
        media_type = str(package.get("media_type") or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or not re.fullmatch(r"[a-f0-9]{64}", digest) or media_type not in {"application/json", "application/yaml"}:
            raise CatalogError("Benchmark pack package metadata is invalid.")
        author = str(value.get("author") or "").strip()
        source_code_url = str(value.get("source_code_url") or "")
        if not author or len(author) > 160 or urlparse(source_code_url).scheme != "https":
            raise CatalogError("Benchmark pack author or source is invalid.")
        return {
            "content_type": "benchmark_pack",
            "identity": {"id": pack_id, "version": version},
            "pack": {"id": pack_id, "version": version, "schema_version": schema_version, "category": category, "name": str(pack.get("name") or pack_id)[:160]},
            "author": author,
            "source_code_url": source_code_url,
            "package": {"url": package_url, "sha256": digest, "size": self._size(package.get("size")), "media_type": media_type},
            "compatible": True,
            "platform_supported": True,
            "permissions": [],
            "reputation": "unverified",
            "requires_permission_review": False,
            "executable": False,
        }

    def _workflow_entry(self, value: dict[str, Any]) -> dict[str, Any]:
        template = value.get("template")
        package = value.get("package")
        if not isinstance(template, dict) or not isinstance(package, dict):
            raise CatalogError("Workflow template metadata is invalid.")
        template_id = str(template.get("id") or "")
        version = str(template.get("version") or "")
        schema_version = str(template.get("schema_version") or "")
        prerequisites = template.get("prerequisites")
        gates = template.get("gate_ids")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", template_id) or not re.fullmatch(r"\d+\.\d+\.\d+", version) or schema_version != "1.0" or not isinstance(prerequisites, list) or not prerequisites or not isinstance(gates, list) or not gates:
            raise CatalogError("Workflow template identity or prerequisites are invalid.")
        package_url = str(package.get("url") or "")
        parsed = urlparse(package_url)
        digest = str(package.get("sha256") or "")
        media_type = str(package.get("media_type") or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or not re.fullmatch(r"[a-f0-9]{64}", digest) or media_type not in {"application/json", "application/yaml"}:
            raise CatalogError("Workflow template package metadata is invalid.")
        author = str(value.get("author") or "").strip()
        source_code_url = str(value.get("source_code_url") or "")
        if not author or len(author) > 160 or urlparse(source_code_url).scheme != "https":
            raise CatalogError("Workflow template author or source is invalid.")
        return {"content_type": "workflow_template", "identity": {"id": template_id, "version": version}, "template": {"id": template_id, "version": version, "schema_version": schema_version, "name": str(template.get("name") or template_id)[:160], "prerequisites": prerequisites, "gate_ids": gates}, "author": author, "source_code_url": source_code_url, "package": {"url": package_url, "sha256": digest, "size": self._size(package.get("size")), "media_type": media_type}, "compatible": True, "platform_supported": True, "permissions": [], "reputation": "unverified", "requires_permission_review": False, "executable": False}

    def _timestamp(self, value: Any, name: str) -> datetime:
        if not isinstance(value, str):
            raise CatalogError(f"Catalog {name} is invalid.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CatalogError(f"Catalog {name} is invalid.") from exc
        if parsed.tzinfo is None:
            raise CatalogError(f"Catalog {name} must include a timezone.")
        return parsed.astimezone(timezone.utc)

    def _size(self, value: Any) -> int:
        if not isinstance(value, int) or value <= 0 or value > 100 * 1024 * 1024:
            raise CatalogError("Plugin package size is invalid.")
        return value


plugin_catalog = PluginCatalog()
