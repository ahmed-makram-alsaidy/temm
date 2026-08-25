import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import select

from ..errors import DomainError
from ..storage.models import WorkflowTemplateVersionRecord
from ..workflow_contract import WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowPort


class WorkflowTemplateMarketplaceService:
    async def import_payload(self, session, payload: dict[str, Any], source_uri: str) -> WorkflowTemplateVersionRecord:
        normalized = self.validate(payload)
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        content_hash = hashlib.sha256(encoded).hexdigest()
        existing = (await session.execute(select(WorkflowTemplateVersionRecord).where(WorkflowTemplateVersionRecord.content_hash == content_hash))).scalar_one_or_none()
        if existing:
            return existing
        duplicate = (await session.execute(select(WorkflowTemplateVersionRecord).where(WorkflowTemplateVersionRecord.template_key == normalized["template_key"], WorkflowTemplateVersionRecord.version == normalized["version"]))).scalar_one_or_none()
        if duplicate:
            raise DomainError("resource_conflict", message="Workflow template version already exists with different content.")
        record = WorkflowTemplateVersionRecord(
            id=f"workflow-template-{uuid.uuid4().hex[:12]}",
            template_key=normalized["template_key"],
            version=normalized["version"],
            name=normalized["name"],
            definition_json=json.dumps(normalized["definition"], sort_keys=True),
            prerequisites_json=json.dumps(normalized["prerequisites"]),
            gate_ids_json=json.dumps(normalized["gate_ids"]),
            provenance="marketplace",
            source_uri=source_uri,
            content_hash=content_hash,
            executable=False,
        )
        session.add(record)
        await session.commit()
        return record

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or payload.get("executable") not in {None, False}:
            raise DomainError("validation_failed", message="Workflow template schema or executable claim is invalid.")
        key = str(payload.get("template_key") or "").strip().lower()
        version = str(payload.get("version") or "")
        name = str(payload.get("name") or "").strip()
        prerequisites = self._strings(payload.get("prerequisites"), "prerequisites")
        gates = self._strings(payload.get("gate_ids"), "gates")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", key) or not re.fullmatch(r"\d+\.\d+\.\d+", version) or not name or len(name) > 160:
            raise DomainError("validation_failed", message="Workflow template identity is invalid.")
        definition_value = payload.get("definition")
        if not isinstance(definition_value, dict):
            raise DomainError("validation_failed", message="Workflow definition is invalid.")
        nodes_value = definition_value.get("nodes")
        edges_value = definition_value.get("edges", [])
        if not isinstance(nodes_value, list) or not 1 <= len(nodes_value) <= 100 or not isinstance(edges_value, list) or len(edges_value) > 500:
            raise DomainError("validation_failed", message="Workflow template size is invalid.")
        nodes = [self._node(item) for item in nodes_value]
        edges = [self._edge(item) for item in edges_value]
        inputs = [self._port(item) for item in definition_value.get("inputs", [])]
        outputs = [self._port(item) for item in definition_value.get("outputs", [])]
        definition = WorkflowDefinition(key, version, nodes, edges, inputs, outputs).validate()
        normalized_definition = {
            "workflow_id": definition.workflow_id,
            "version": definition.version,
            "nodes": [self._node_dict(item) for item in definition.nodes],
            "edges": [self._edge_dict(item) for item in definition.edges],
            "inputs": [self._port_dict(item) for item in definition.inputs],
            "outputs": [self._port_dict(item) for item in definition.outputs],
        }
        return {"schema_version": "1.0", "template_key": key, "version": version, "name": name, "prerequisites": prerequisites, "gate_ids": gates, "definition": normalized_definition, "executable": False}

    def _node(self, value: Any) -> WorkflowNode:
        if not isinstance(value, dict):
            raise DomainError("validation_failed", message="Workflow node is invalid.")
        node_id = str(value.get("id") or "")
        node_type = str(value.get("type") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", node_id) or node_type not in {"task", "agent", "judge", "critic", "gate", "output", "router", "parallel", "condition"}:
            raise DomainError("validation_failed", message="Workflow node identity or type is invalid.")
        capabilities = self._optional_strings(value.get("required_capabilities", []))
        permissions = self._optional_strings(value.get("permissions", []))
        retry = value.get("retry", {})
        if not isinstance(retry, dict):
            raise DomainError("validation_failed", message="Workflow retry is invalid.")
        return WorkflowNode(node_id, node_type, [self._port(item) for item in value.get("inputs", [])], [self._port(item) for item in value.get("outputs", [])], capabilities, permissions, retry)

    def _edge(self, value: Any) -> WorkflowEdge:
        if not isinstance(value, dict):
            raise DomainError("validation_failed", message="Workflow edge is invalid.")
        condition = value.get("condition", {})
        if not isinstance(condition, dict):
            raise DomainError("validation_failed", message="Workflow edge condition is invalid.")
        return WorkflowEdge(str(value.get("source_node") or ""), str(value.get("source_port") or ""), str(value.get("target_node") or ""), str(value.get("target_port") or ""), condition)

    def _port(self, value: Any) -> WorkflowPort:
        if not isinstance(value, dict) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", str(value.get("name") or "")) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", str(value.get("data_type") or "")):
            raise DomainError("validation_failed", message="Workflow port is invalid.")
        return WorkflowPort(str(value["name"]), str(value["data_type"]), bool(value.get("required", True)))

    def _strings(self, value: Any, label: str) -> list[str]:
        result = self._optional_strings(value)
        if not result:
            raise DomainError("validation_failed", message=f"Workflow template {label} are required.")
        return result

    def _optional_strings(self, value: Any) -> list[str]:
        if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in value):
            raise DomainError("validation_failed", message="Workflow template string list is invalid.")
        return list(dict.fromkeys(item.strip() for item in value))

    def _port_dict(self, item: WorkflowPort): return {"name": item.name, "data_type": item.data_type, "required": item.required}
    def _node_dict(self, item: WorkflowNode): return {"id": item.node_id, "type": item.node_type, "inputs": [self._port_dict(port) for port in item.inputs], "outputs": [self._port_dict(port) for port in item.outputs], "required_capabilities": item.required_capabilities, "permissions": item.permissions, "retry": item.retry}
    def _edge_dict(self, item: WorkflowEdge): return {"source_node": item.source_node, "source_port": item.source_port, "target_node": item.target_node, "target_port": item.target_port, "condition": item.condition}


workflow_template_marketplace_service = WorkflowTemplateMarketplaceService()
