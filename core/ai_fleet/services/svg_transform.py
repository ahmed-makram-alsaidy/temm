import re
import xml.etree.ElementTree as ET

from ..errors import DomainError


class SvgTransformService:
    def sanitize(self, content: str) -> dict:
        if len(content.encode()) > 5 * 1024 * 1024 or re.search(r"<!DOCTYPE|<!ENTITY", content, re.IGNORECASE):
            raise DomainError("validation_failed", message="SVG declaration or size is unsafe.")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise DomainError("validation_failed", message="SVG is malformed.") from exc
        if self._local(root.tag) != "svg":
            raise DomainError("validation_failed", message="Document root is not SVG.")
        report = {"removed_elements": [], "removed_attributes": [], "external_references_removed": 0}
        self._sanitize_node(root, report)
        output = ET.tostring(root, encoding="unicode", short_empty_elements=True)
        return {"content": output, "report": report, "sanitized": any(report.values()), "transform_version": "1.0"}

    def _sanitize_node(self, node, report):
        for child in list(node):
            name = self._local(child.tag).lower()
            if name in {"script", "foreignobject", "iframe", "object", "embed"}:
                node.remove(child)
                report["removed_elements"].append(name)
            else:
                self._sanitize_node(child, report)
        for key, value in list(node.attrib.items()):
            local = self._local(key).lower()
            lowered = value.strip().lower()
            external = local in {"href", "src"} and not lowered.startswith(("#", "data:")) or "url(" in lowered and not re.fullmatch(r"url\(\s*#[^)]+\s*\)", lowered)
            if local.startswith("on") or local == "style" and re.search(r"expression\s*\(|javascript:", lowered):
                del node.attrib[key]
                report["removed_attributes"].append(local)
            elif external or "javascript:" in lowered:
                del node.attrib[key]
                report["removed_attributes"].append(local)
                report["external_references_removed"] += 1

    def _local(self, value):
        return value.rsplit("}", 1)[-1]


svg_transform_service = SvgTransformService()
