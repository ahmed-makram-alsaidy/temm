import json
import uuid
from typing import Any, Dict

from ..blueprints import BlueprintTemplate
from ..errors import DomainError
from .provider_runtime import ProviderRuntimeRegistry


class BlueprintGenerationService:
    def __init__(self, registry: ProviderRuntimeRegistry): self._registry = registry

    async def generate(self, template: BlueprintTemplate, goal: str, evidence: Dict[str, Any], provider: str, model_id: str) -> Dict[str, Any]:
        template.validate()
        if not goal.strip() or len(goal) > 100000 or len(json.dumps(evidence).encode()) > 500000: raise DomainError("validation_failed", message="Blueprint goal or evidence is invalid.")
        prompt = "Propose a structured project blueprint. Return one JSON object with requirements and questions arrays. Requirements need section_id, title, description, requirement_type, priority, acceptance. Questions need section_id, text, required. Everything is a proposal requiring owner approval.\n" + json.dumps({"goal": goal, "evidence": evidence, "template": template.to_dict()}, ensure_ascii=False)
        chunks = []; error = None
        async for event in self._registry.resolve(provider).stream(model_id, prompt, f"blueprint-{uuid.uuid4().hex[:12]}"):
            if event.event_type == "chunk": chunks.append(event.text)
            elif event.event_type in {"error", "cancelled"}: error = event.error_code or event.event_type
        if error: raise DomainError("execution_failed", message="Blueprint provider execution failed.", details={"error_code": error})
        try: payload = json.loads("".join(chunks))
        except json.JSONDecodeError as exc: raise DomainError("validation_failed", message="Blueprint provider returned invalid JSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("requirements", []), list) or not isinstance(payload.get("questions", []), list) or len(payload.get("requirements", [])) > 500 or len(payload.get("questions", [])) > 200:
            raise DomainError("validation_failed", message="Blueprint proposal structure is invalid.")
        sections = {section.section_id for section in template.sections}; requirements = []; questions = []
        for item in payload.get("requirements", []):
            if not isinstance(item, dict) or item.get("section_id") not in sections or not all(isinstance(item.get(key), str) and item[key].strip() for key in ["title", "description", "requirement_type", "priority"]) or not isinstance(item.get("acceptance", []), list): raise DomainError("validation_failed", message="Blueprint requirement proposal is invalid.")
            requirements.append({"proposal_id": f"proposal-{uuid.uuid4().hex[:12]}", "section_id": item["section_id"], "title": item["title"], "description": item["description"], "requirement_type": item["requirement_type"], "priority": item["priority"], "acceptance": item.get("acceptance", []), "truth_state": "proposed", "status": "proposed", "provenance": "model_proposed", "approved": False})
        for item in payload.get("questions", []):
            if not isinstance(item, dict) or item.get("section_id") not in sections or not isinstance(item.get("text"), str) or not item["text"].strip(): raise DomainError("validation_failed", message="Blueprint question proposal is invalid.")
            questions.append({"question_id": f"proposal-question-{uuid.uuid4().hex[:12]}", "section_id": item["section_id"], "text": item["text"], "required": bool(item.get("required", False)), "status": "proposed", "provenance": "model_proposed"})
        return {"template_id": template.template_id, "template_version": template.version, "goal": goal, "requirements": requirements, "questions": questions, "approval_required": True, "implementation_started": False, "provider": provider, "model_id": model_id}
