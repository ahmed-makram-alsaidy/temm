"""Execution preflight for real provider and authenticated CLI routes."""

from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..storage.database import AsyncSessionLocal
from ..storage.models import AgentRecord, ModelRecord, WorkspaceRecord
from ..services.model_registry import model_registry_service
from ..routing import RoutingCandidate, RoutingEvidence, RoutingRequest, unknown_evidence
from ..services.route_explanation import route_explanation_service
from ..services.route_selection import executable_route_selection_service
from .host_capacity import host_capacity
from .process_manager import process_manager
from ..permissions import permission_policy
from .router import model_router
from .scanner import system_scanner

def _serving_capability(agent: AgentRecord, category: str) -> Optional[str]:
    """Return the declared capability through which the agent serves `category`."""
    capabilities = agent.to_dict().get("capabilities", [])
    if category == "coding":
        return "coding" if "coding" in capabilities else None
    if category in capabilities:
        return category
    return "general" if "general" in capabilities else None


def _agent_supports(agent: AgentRecord, category: str) -> bool:
    return _serving_capability(agent, category) is not None


def _known(value, provenance, observed_at=None, source_id=None):
    return RoutingEvidence(value, provenance, observed_at=observed_at, source_id=source_id)


def _agent_candidate(agent: AgentRecord, category: str) -> RoutingCandidate:
    capabilities = agent.to_dict().get("capabilities", [])
    observed_at = agent.last_checked_at.isoformat() if agent.last_checked_at else None
    executable = agent.tool_kind == "agent" and agent.user_enabled and agent.lifecycle_status == "active" and agent.auth_state in {"not_required", "verified"} and agent.discovery_state == "verified" and agent.status == "ready"
    blockers = [] if executable else ["agent_not_ready"]
    declared = {item: _known(True, "measured", observed_at, agent.id) for item in capabilities}
    # Route selection asks for a capability by the task's category name, while the fleet
    # declares capabilities. `_serving_capability` is the single policy that decides
    # whether a declared CLI serves a category, so the candidate has to publish the same
    # answer. Without this, the two halves of one engine disagreed: a verified coding CLI
    # was rejected as `missing_capability:reasoning` for a category the same policy had
    # already said it serves, so no route could ever be handed out for it.
    serving = _serving_capability(agent, category) if category else None
    if serving and category not in declared:
        declared[category] = RoutingEvidence(True, "measured", observed_at=observed_at, source_id=agent.id, reason=f"served_by_declared_{serving}")
    return RoutingCandidate(
        route_id=f"agent:{agent.id}", agent_id=agent.id, model_id=None, provider_instance_id=None,
        capabilities=declared,
        availability=_known(True, "measured", observed_at, agent.id) if executable else unknown_evidence("agent_not_ready"),
        benchmark=unknown_evidence("comparable_benchmark_missing"), estimated_cost=unknown_evidence("agent_cost_unknown"), speed=unknown_evidence("agent_speed_missing"), reliability=unknown_evidence("agent_reliability_missing"), context_capacity=unknown_evidence("agent_context_unknown"), executable=executable, blockers=blockers,
    )


def _model_candidate(model: ModelRecord, assessment: Dict[str, Any]) -> RoutingCandidate:
    payload = model.to_dict(); provenance = payload.get("capability_provenance")
    score_provenance = provenance if provenance in {"measured", "provider_reported"} else None
    capabilities = {payload["category"]: _known(True, "provider_reported" if score_provenance == "provider_reported" else "user_declared", payload.get("source_checked_at"), model.id)}
    if payload["category"] != "general": capabilities["general"] = _known(True, "user_declared", payload.get("source_checked_at"), model.id)
    return RoutingCandidate(
        route_id=f"provider:{model.provider}:{model.id}", agent_id=None, model_id=model.id, provider_instance_id=model.provider,
        capabilities=capabilities,
        availability=_known(True, "measured", payload.get("availability_checked_at"), model.id) if assessment["executable"] else unknown_evidence(assessment["code"]),
        benchmark=_known(payload["quality_score"], score_provenance, payload.get("source_checked_at"), model.id) if payload["quality_score"] is not None and score_provenance else unknown_evidence("comparable_benchmark_missing"),
        estimated_cost=unknown_evidence("task_cost_not_resolved"),
        speed=_known(payload["speed_score"], score_provenance, payload.get("source_checked_at"), model.id) if payload["speed_score"] is not None and score_provenance else unknown_evidence("speed_sample_missing"),
        reliability=_known(payload["reliability_score"], score_provenance, payload.get("source_checked_at"), model.id) if payload["reliability_score"] is not None and score_provenance else unknown_evidence("reliability_sample_missing"),
        context_capacity=_known(payload["context_window"], "provider_reported", payload.get("source_checked_at"), model.id) if payload["context_window"] else unknown_evidence("context_capacity_unknown"),
        executable=assessment["executable"], blockers=[] if assessment["executable"] else [assessment["code"]],
    )


async def build_execution_preflight(
    prompt: str,
    routing_mode: str = "balanced",
    model_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    interactive: bool = False,
    required_capabilities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return the actual executable route, installed tools, and setup blockers."""
    scan = await system_scanner.scan_system()
    configured = scan["configured_providers"]
    recommendation = await model_router.recommend_model(prompt=prompt, mode=routing_mode)
    task_analysis = recommendation["task_analysis"]
    # A persisted TEMM task already states what its executor must be able to do, and the
    # dispatcher selects against exactly that contract. Re-deriving the requirement from
    # the task's prose made the gate demand a different capability than the dispatcher
    # would, so an approved project could never become ready even with a verified,
    # permitted executor bound to an approved workspace. The prose reading stays as the
    # fallback for ad-hoc prompts, which carry no contract of their own.
    contract = [item for item in (required_capabilities or []) if isinstance(item, str) and item.strip()]
    routing_category = contract[0] if contract else task_analysis["category"]
    required = contract or [routing_category]

    async with AsyncSessionLocal() as session:
        models = (await session.execute(select(ModelRecord).where(ModelRecord.is_active == True))).scalars().all()
        agents = (await session.execute(select(AgentRecord))).scalars().all()
        workspaces = (await session.execute(select(WorkspaceRecord))).scalars().all()

    discovered_by_id = {tool["id"]: tool for tool in scan["discovered_tools"]}
    agent_by_id = {agent.id: agent for agent in agents}
    installed_tools: List[Dict[str, Any]] = []
    for agent in agents:
        discovered = discovered_by_id.get(agent.id, {})
        if not agent.is_installed and not discovered:
            continue
        payload = agent.to_dict()
        payload["auth_status"] = agent.auth_state
        payload["auth_message"] = agent.to_dict().get("auth_evidence", {}).get("reason", "")
        payload["setup_action"] = agent.to_dict().get("auth_setup_action", {})
        installed_tools.append(payload)

    selected_agent: Optional[AgentRecord] = None
    workspace_by_id = {workspace.id: workspace for workspace in workspaces}
    selected_workspace = workspace_by_id.get(workspace_id) if workspace_id else next((workspace for workspace in workspaces if workspace.is_default), None)
    requested_agent_id = agent_id if agent_id and agent_id != "auto" else None
    if requested_agent_id:
        candidate = agent_by_id.get(requested_agent_id)
        if candidate and candidate.tool_kind == "agent" and candidate.user_enabled and candidate.lifecycle_status == "active" and candidate.auth_state in {"not_required", "verified"} and candidate.discovery_state == "verified" and candidate.status == "ready":
            selected_agent = candidate
    elif not model_id or model_id == "auto":
        ordered_agents = sorted(
            agents,
            key=lambda agent: (agent.discovery_source != "manual", agent.name.lower()),
        )
        selected_agent = next(
            (
                agent
                for agent in ordered_agents
                if agent.tool_kind == "agent" and agent.user_enabled and agent.lifecycle_status == "active" and agent.auth_state in {"not_required", "verified"} and agent.discovery_state == "verified" and agent.status == "ready" and all(_agent_supports(agent, item) for item in required)
            ),
            None,
        )

    recommended_id = recommendation["selected_model"]["id"]
    model_by_id = {model.id: model for model in models}
    requested_model_id = model_id if model_id and model_id != "auto" else None
    ordered_model_ids: List[str] = []
    if requested_model_id:
        ordered_model_ids.append(requested_model_id)
    else:
        ordered_model_ids.extend(recommendation.get("fallback_chain", []))
        ordered_model_ids.extend(model.id for model in models)
    ordered_model_ids = list(dict.fromkeys(ordered_model_ids))

    selected_model: Optional[ModelRecord] = None
    model_states: Dict[str, Dict[str, Any]] = {}
    for candidate_id in ordered_model_ids:
        candidate = model_by_id.get(candidate_id)
        if not candidate:
            continue
        assessment = model_registry_service.assess(candidate, configured, scan["ollama_status"])
        model_states[candidate.id] = assessment
        if assessment["executable"] and selected_model is None:
            selected_model = candidate

    if selected_agent and selected_workspace:
        try:
            permission_policy.enforce_agent_workspace(
                selected_agent.permission_profile,
                selected_workspace.permission_profile,
                selected_agent.to_dict().get("capabilities", []),
            )
        except PermissionError:
            selected_agent = None

    pty_capability = process_manager.pty_capability()
    host = host_capacity()
    candidates = []
    agent_candidates = [agent_by_id[requested_agent_id]] if requested_agent_id and requested_agent_id in agent_by_id else agents if not requested_model_id else []
    for candidate_agent in agent_candidates:
        candidate = _agent_candidate(candidate_agent, routing_category)
        candidate_blockers = list(candidate.blockers)
        if not selected_workspace: candidate_blockers.append("workspace_required")
        else:
            try: permission_policy.enforce_agent_workspace(candidate_agent.permission_profile, selected_workspace.permission_profile, candidate_agent.to_dict().get("capabilities", []))
            except PermissionError: candidate_blockers.append("permission_incompatible")
        if interactive and not candidate_agent.supports_interactive: candidate_blockers.append("agent_not_interactive")
        if interactive and not pty_capability["supported"]: candidate_blockers.append("pty_unavailable")
        candidates.append(RoutingCandidate(**{**candidate.__dict__, "executable": not candidate_blockers, "blockers": sorted(set(candidate_blockers))}))
    model_candidates = [model_by_id[requested_model_id]] if requested_model_id and requested_model_id in model_by_id else models if not requested_agent_id else []
    for candidate_model in model_candidates:
        assessment = model_states.get(candidate_model.id) or model_registry_service.assess(candidate_model, configured, scan["ollama_status"])
        candidate = _model_candidate(candidate_model, assessment)
        if interactive:
            candidate = RoutingCandidate(**{**candidate.__dict__, "executable": False, "blockers": sorted(set([*candidate.blockers, "interactive_requires_agent"]))})
        candidates.append(candidate)
    route_decision = None
    route_explanation = None
    execution_method: Optional[str] = None
    selected_agent = None
    selected_model = None
    if candidates:
        request = RoutingRequest(prompt[:64] or "task", routing_category, list(dict.fromkeys(required)), RoutingEvidence(max(1, int(len(prompt.split()) * 1.35)), "estimated", reason="word_count_multiplier"), routing_mode, candidates)
        try:
            route_decision = executable_route_selection_service.select(request)
            route_explanation = route_explanation_service.explain(route_decision)
            selected_route = route_decision["selected_route"]
            if selected_route["agent_id"]:
                selected_agent = agent_by_id[selected_route["agent_id"]]; execution_method = "cli"
            else:
                selected_model = model_by_id[selected_route["model_id"]]; execution_method = "provider_api"
        except Exception as exc:
            if not isinstance(exc, ValueError) and not hasattr(exc, "code"): raise

    blockers: List[Dict[str, Any]] = []
    if not host["sufficient"]:
        # The gate used to report on the provider, the credentials, the workspace and
        # the PTY, and never on the machine underneath them - so a host with no room
        # was described as a route problem by whichever route happened to be selected.
        # This blocks only what genuinely cannot be served; host pressure short of
        # that is carried as an observation under `host`, because a floor on available
        # physical memory would refuse hosts measured to run fine. See host_capacity.
        blockers.append({
            "code": "host_capacity_unavailable",
            "title": "Host out of memory",
            "detail": host["detail"] or "This machine has no room left to host a run.",
            "action_target": "fleet",
        })
        execution_method = None
    elif interactive and execution_method == "provider_api":
        blockers.append({
            "code": "interactive_requires_agent",
            "title": "Interactive terminal unavailable",
            "detail": "Interactive execution requires a local CLI agent with PTY support.",
            "action_target": "fleet",
        })
        execution_method = None
    elif interactive and selected_agent and not selected_agent.supports_interactive:
        blockers.append({
            "code": "agent_not_interactive",
            "title": selected_agent.name,
            "detail": "This agent does not declare interactive PTY support.",
            "action_target": "fleet",
        })
        execution_method = None
    elif interactive and not pty_capability["supported"]:
        blockers.append({
            "code": "pty_unavailable",
            "title": "PTY unavailable",
            "detail": pty_capability["reason"] or "No PTY backend is available on this host.",
            "action_target": "fleet",
        })
        execution_method = None

    if not execution_method:
        if selected_agent and not selected_workspace:
            blockers.append({
                "code": "workspace_required",
                "title": "Workspace required",
                "detail": "Choose an approved workspace before an agent can read or change files.",
                "action_target": "workspaces",
            })
        if requested_agent_id and not selected_agent:
            requested_agent = agent_by_id.get(requested_agent_id)
            auth_blocked = requested_agent and requested_agent.discovery_state == "verified" and requested_agent.auth_state not in {"not_required", "verified"}
            blockers.append({
                "code": "agent_auth_unverified" if auth_blocked else "agent_unavailable",
                "title": requested_agent.name if requested_agent else requested_agent_id,
                "detail": "Authentication is required but has not been verified." if auth_blocked else "The selected CLI is not currently executable.",
                "action_target": "fleet",
            })

        unavailable_model_id = requested_model_id or recommended_id
        unavailable_model = model_by_id.get(unavailable_model_id)
        state = model_states.get(unavailable_model_id)
        if unavailable_model and state and not state["executable"]:
            provider = model_registry_service.canonical_provider(unavailable_model)
            blockers.append({
                "code": state["code"],
                "title": unavailable_model.name,
                "detail": state["detail"],
                "provider": provider,
                "action_target": "settings" if state["code"] == "provider_not_configured" else "fleet",
            })

        for tool in installed_tools:
            if tool.get("auth_status") not in {"not_required", "verified"}:
                blockers.append({
                    "code": "agent_auth_unverified",
                    "title": tool["name"],
                    "detail": tool.get("auth_message") or "Authentication is required but has not been verified.",
                    "setup_action": tool.get("setup_action"),
                    "action_target": "fleet",
                })

    return {
        "can_execute": execution_method is not None,
        "execution_method": execution_method,
        "required_capabilities": list(dict.fromkeys(required)),
        "capability_basis": "task_contract" if contract else "prompt_analysis",
        "recommendation": recommendation,
        "route_decision": route_decision,
        "route_explanation": route_explanation,
        "selected_model": selected_model.to_dict() if selected_model else None,
        "selected_agent": selected_agent.to_dict() if selected_agent else None,
        "selected_workspace": selected_workspace.to_dict() if selected_workspace else None,
        "workspaces": [workspace.to_dict() for workspace in workspaces],
        "recommended_model": recommendation["selected_model"],
        "recommended_model_state": model_states.get(recommended_id, {"state": "catalog", "executable": False, "code": "unknown", "detail": "Availability was not verified."}),
        "blockers": blockers,
        "installed_tools": installed_tools,
        "connections": configured,
        "ollama_status": scan["ollama_status"],
        "pty": pty_capability,
        "host": host,
        "interactive": interactive,
    }
