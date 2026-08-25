from typing import Any, Dict, List

from ..context import ContextSource, ContextSourceType


class ContextRelevanceService:
    def select(self, sources: List[ContextSource], task: Dict[str, Any], impacted_requirement_ids: List[str]) -> Dict[str, Any]:
        explicit = set(task.get("source_ids", [])); requirements = set(task.get("requirement_ids", [])); impacted = set(impacted_requirement_ids); component = task.get("component"); project_id = task.get("project_id")
        selected = []; excluded = []
        for source in sorted(sources, key=lambda item: (item.source_type.value, item.source_id, item.version)):
            source.validate(); reason = None; priority = None
            if source.source_id in explicit: reason, priority = "explicit_source", 0
            elif source.source_type == ContextSourceType.REQUIREMENT and source.source_id in requirements: reason, priority = "linked_requirement", 1
            elif source.source_type == ContextSourceType.REQUIREMENT and source.source_id in impacted: reason, priority = "requirement_impact", 2
            elif source.source_type == ContextSourceType.DECISION and source.metadata.get("status") == "approved" and (source.metadata.get("scope_type") == "project" or source.metadata.get("scope_id") == component): reason, priority = "active_decision_scope", 3
            elif source.project_id == project_id and source.metadata.get("always_include") is True: reason, priority = "project_required_source", 4
            if reason is not None: selected.append({"source": source.to_dict(), "reason": reason, "priority": priority})
            else: excluded.append({"source_type": source.source_type.value, "source_id": source.source_id, "reason": "no_explicit_graph_relevance"})
        selected.sort(key=lambda item: (item["priority"], item["source"]["source_type"], item["source"]["source_id"]))
        return {"selected": selected, "excluded": excluded, "selector_version": "1.0", "deterministic": True}


context_relevance_service = ContextRelevanceService()
