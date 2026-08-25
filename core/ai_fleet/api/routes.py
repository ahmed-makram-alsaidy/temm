"""FastAPI API Routers for TEMM with Real Execution Engine and Chat Studio."""

import asyncio
import json
import os
import sys
import uuid
import time
import re
import yaml
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, delete, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.database import get_db, AsyncSessionLocal
from ..storage.models import (
    ProviderInstanceRecord,
    ModelRecord,
    AgentRecord,
    TaskRun,
    RunAttemptRecord,
    ChatSession,
    ChatMessage,
    BenchmarkRecord,
    DelegateSkillRecord,
    WorkflowRecord,
    WorkflowTemplateVersionRecord,
    SubscriptionRecord,
    SystemSetting,
    BudgetRecord,
    WorkspaceRecord,
    CommandRunRecord,
    PluginRecord,
    PluginCatalogSourceRecord,
    ApprovalRecord,
    AssetRecord,
    AssetUsageRecord,
    AssetTransformJobRecord,
    ResearchQueryRecord,
    ResearchSourceRecord,
    ResearchClaimRecord,
    ResearchCitationRecord,
    DeliverableRecord,
    OrchestrationCheckpointRecord,
    OrchestrationTaskRecord,
    ProjectNeedRecord,
    ProjectRecord,
    ProjectRequirementRecord,
    ProjectDecisionRecord,
)
from ..storage.secret_vault import secret_vault
from ..services.agent_lifecycle import AgentLifecycleError, AgentLifecycleService
from ..services.settings import settings_service
from ..services.model_lifecycle import model_lifecycle_service
from ..services.model_registry import model_registry_service
from ..services.pricing import pricing_service
from ..services.financials import CostResult, cost_calculator, savings_calculator
from ..services.budgets import budget_service
from ..services.analytics import analytics_service
from ..services.run_comparison import run_comparison_service
from ..services.model_favorites import model_favorite_service
from ..services.model_history import model_history_service
from ..services.telemetry_export import telemetry_export_service
from ..services.benchmark_suites import benchmark_suite_service
from ..services.benchmark_packs import benchmark_pack_service
from ..services.benchmark_runner import benchmark_runner_service
from ..services.arena import arena_service
from ..services.leaderboards import personal_leaderboard_service
from ..services.community_leaderboards import community_leaderboard_service
from ..services.efficiency import efficiency_service
from ..services.projects import project_service
from ..services.project_workspaces import project_workspace_service
from ..services.project_brain import project_brain_service
from ..services.decisions import decision_service
from ..services.requirements import requirement_service
from ..services.blueprint_approval import blueprint_approval_service
from ..services.context_packs import context_pack_service
from ..services.asset_library import asset_library_service
from ..services.asset_validation import asset_validation_service
from ..services.media_transform import MediaTransformService
from ..services.quality_workspace import quality_workspace_service
from ..services.orchestration_commands import orchestration_command_service
from ..services.project_dispatcher import ProjectDispatcherService
from ..services.plan_compiler import plan_compiler_service
from ..services.completion_assessment import completion_assessment_service
from ..website_blueprint import WEBSITE_TEMPLATE
from ..business_blueprint import BUSINESS_SYSTEM_TEMPLATE
from ..services.requirement_readiness import requirement_readiness_service
from ..services.requirement_graph import requirement_graph_service
from ..services.automation_value import automation_value_service
from ..services.needs_value import needs_value_service
from ..services.rework_value import rework_value_service
from ..services.baseline import baseline_service
from ..services.capability_evidence import capability_evidence_service
from ..services.provider_registry import provider_registry_service
from ..services.provider_runtime import provider_runtime_registry
from ..services.usage import usage_service
from ..services.latency import latency_service
from ..services.quota import quota_service
from ..services.runs import run_lifecycle_service
from ..services.run_output import run_output_service
from ..services.run_artifacts import run_artifact_service
from ..services.event_journal import event_journal
from ..services.plugin_runtime import PluginRuntimeService
from ..services.plugin_conformance import PluginConformanceService
from ..services.plugin_marketplace import PluginMarketplaceService
from ..services.approvals import approval_service
from ..services.audit import audit_service
from ..domain import CAPABILITY_SCHEMA_VERSION, DOMAIN_DEFINITIONS, DOMAIN_SCHEMA_VERSION, STATE_SCHEMA_VERSION, CAPABILITIES
from ..errors import DomainError, ERROR_DEFINITIONS, ERROR_SCHEMA_VERSION
from ..filesystem import PathPolicyError, path_policy
from ..plugin_protocol import PluginManifest, negotiate_protocol
from ..plugin_permissions import plugin_permission_policy
from ..plugin_package import PluginPackageError, contained_entrypoint, hash_plugin_folder
from ..cli_invocation import build_cli_args
from ..url_safety import url_safety_service
from ..discovery.adapters import validate_probe_args
from ..engine.scanner import system_scanner
from ..engine.router import model_router
from ..engine.benchmark_engine import benchmark_engine
from ..engine.skill_adapter import skill_adapter
from ..engine.workflow_engine import workflow_engine
from ..engine.process_manager import DuplicateTaskIdError, process_manager
from ..engine.event_bus import task_event_bus
from ..engine.execution_readiness import build_execution_preflight
from ..engine.host_capacity import host_capacity

# --- Fleet Overview Router ---
fleet_router = APIRouter(prefix="/api/fleet", tags=["Fleet"])
health_router = APIRouter(prefix="/health", tags=["Health"])


@fleet_router.get("/domain-contract")
async def get_domain_contract():
    return {
        "domain_schema_version": DOMAIN_SCHEMA_VERSION,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "state_schema_version": STATE_SCHEMA_VERSION,
        "domains": [
            {
                "kind": definition.kind.value,
                "responsibility": definition.responsibility,
                "identity_scope": definition.identity_scope,
                "may_execute": definition.may_execute,
            }
            for definition in DOMAIN_DEFINITIONS.values()
        ],
        "capabilities": sorted(CAPABILITIES),
        "error_schema_version": ERROR_SCHEMA_VERSION,
        "error_codes": [
            {
                "code": definition.code,
                "category": definition.category.value,
                "status_code": definition.status_code,
                "retryable": definition.retryable,
            }
            for definition in ERROR_DEFINITIONS.values()
        ],
    }


@fleet_router.get("/health/live")
@health_router.get("/live")
async def health_live():
    return {"status": "alive"}


@fleet_router.get("/health/ready")
@health_router.get("/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        integrity = (await db.execute(text("PRAGMA integrity_check"))).scalar_one()
        migrations = [row[0] for row in (await db.execute(text("SELECT version FROM schema_migrations ORDER BY version"))).all()]
        agent_count = len((await db.execute(
            select(AgentRecord).where(
                AgentRecord.tool_kind == "agent",
                AgentRecord.user_enabled == True,
                AgentRecord.lifecycle_status == "active",
                AgentRecord.discovery_state == "verified",
                AgentRecord.auth_state.in_(["not_required", "verified"]),
            )
        )).scalars().all())
        database_ready = integrity == "ok"
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": {"ready": False, "error": type(exc).__name__}})
    frontend_path = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist" / "index.html"
    pty = process_manager.pty_capability()
    # Readiness described the database, the frontend, the agents and the PTY, and never
    # the machine all four run on, so during the memory incident of 2026-08-21 this
    # endpoint reported `ready` while every dispatch was dying before its first model
    # step. The status itself stays `ready`: the API is serving correctly and a shortage
    # passes, so failing readiness would only invite a supervisor to restart a process
    # that is not the problem. It is degraded execution capacity, which is what
    # `degraded` already means for a fleet with no verified agent.
    host = host_capacity()
    return {
        "status": "ready" if database_ready else "not_ready",
        "database": {"ready": database_ready, "integrity": integrity, "migrations": migrations},
        "frontend": {"ready": frontend_path.exists()},
        "execution": {"verified_agents": agent_count, "pty": pty, "host": host, "degraded": agent_count == 0 or not host["sufficient"]},
    }


@fleet_router.get("/overview")
async def get_fleet_overview(db: AsyncSession = Depends(get_db)):
    """Fetch complete top-level command center dashboard metrics."""
    models_res = await db.execute(select(ModelRecord))
    models = models_res.scalars().all()

    agents_res = await db.execute(select(AgentRecord))
    agents = agents_res.scalars().all()

    skills_res = await db.execute(select(DelegateSkillRecord))
    skills = skills_res.scalars().all()

    wf_res = await db.execute(select(WorkflowRecord))
    workflows = wf_res.scalars().all()

    workspace_res = await db.execute(select(WorkspaceRecord))
    workspaces = workspace_res.scalars().all()

    configured = secret_vault.list_configured_providers()
    ollama_status = await system_scanner.inspect_runtime_service()
    executable_providers = {"openai", "anthropic", "google", "groq", "deepseek"}

    def model_is_online(model: ModelRecord) -> bool:
        provider = model.provider.lower()
        if provider in {"gemini"} or "gemini" in model.id.lower():
            provider = "google"
        if provider in {"claude"} or "claude" in model.id.lower():
            provider = "anthropic"
        if provider == "ollama" or model.is_local:
            return bool(ollama_status.get("running") and ollama_status.get("models"))
        return provider in executable_providers and bool(configured.get(provider, {}).get("is_configured"))

    online_models = [m for m in models if m.is_active and model_is_online(m)]
    online_agents = [a for a in agents if a.tool_kind == "agent" and a.user_enabled and a.lifecycle_status == "active" and a.auth_state in {"not_required", "verified"} and a.discovery_state == "verified" and a.status == "ready"]
    connected_providers = sum(
        1 for provider, state in configured.items()
        if provider in executable_providers and state.get("is_configured")
    ) + (1 if ollama_status.get("running") else 0)

    return {
        "fleet_counts": {
            "models_total": len(models),
            "models_online": len(online_models),
            "models_unavailable": len(models) - len(online_models),
            "agents_total": len(agents),
            "agents_ready": len(online_agents),
            "skills_total": len(skills),
            "workflows_total": len(workflows),
            "providers_count": connected_providers,
            "models_registered": len(models),
            "providers_registered": len(set(m.provider for m in models)),
            "workspaces_count": len(workspaces),
            "execution_ready": bool(online_models or (online_agents and workspaces)),
        },
        "operational_metrics": {"source": "canonical_analytics", "endpoint": "/api/analytics/summary", "financials": None, "tokens": None, "tasks": None},
    }


# --- Models Router ---
models_router = APIRouter(prefix="/api/models", tags=["Models"])


# --- System Settings Router ---
settings_router = APIRouter(prefix="/api/settings", tags=["Settings"])
budgets_router = APIRouter(prefix="/api/budgets", tags=["Budgets"])
analytics_router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


class RetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=1, le=3650)


@analytics_router.get("/export")
async def export_telemetry(start: datetime, end: datetime, format: str = Query(default="json", pattern="^(json|csv)$"), db: AsyncSession = Depends(get_db)):
    try:
        content = await telemetry_export_service.export(db, start, end, format)
        media_type = "application/json" if format == "json" else "text/csv"
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="ai-fleet-telemetry.{format}"'})
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@analytics_router.post("/retention/apply")
async def apply_telemetry_retention(request: RetentionRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await telemetry_export_service.apply_retention(db, request.days)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@analytics_router.get("/summary")
async def get_analytics_summary(start: datetime, end: datetime, db: AsyncSession = Depends(get_db)):
    try:
        return await analytics_service.aggregate(db, start, end)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class BudgetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=64)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    period: str = Field(default="monthly", max_length=32)
    scope_type: str = Field(default="fleet", max_length=32)
    scope_id: Optional[str] = Field(default=None, max_length=128)
    alert_threshold: float = Field(default=80.0, ge=1, le=100)
    enabled: bool = True


@budgets_router.get("")
async def list_budgets(db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await budget_service.list(db)]


@budgets_router.post("")
async def create_budget(request: BudgetCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await budget_service.create(db, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@budgets_router.get("/{budget_id}/status")
async def get_budget_status(budget_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await budget_service.status(db, budget_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@settings_router.get("")
async def get_system_settings(db: AsyncSession = Depends(get_db)):
    return await settings_service.read(db)


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]


@settings_router.patch("")
async def update_system_settings(req: SettingsUpdateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await settings_service.update(db, req.settings)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ModelFavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_case: str = Field(min_length=2, max_length=64)


@models_router.get("/{model_id}/history")
async def get_model_history(model_id: str, since: datetime, until: datetime, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500), action: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    try:
        return await model_history_service.query(db, model_id, since, until, after, limit, action)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.get("/favorites")
async def list_model_favorites(use_case: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await model_favorite_service.list(db, use_case)]


@models_router.put("/{model_id}/favorites")
async def set_model_favorite(model_id: str, request: ModelFavoriteRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await model_favorite_service.set(db, model_id, request.use_case)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.delete("/{model_id}/favorites/{use_case}")
async def remove_model_favorite(model_id: str, use_case: str, db: AsyncSession = Depends(get_db)):
    try:
        await model_favorite_service.remove(db, model_id, use_case)
        return {"model_id": model_id, "use_case": use_case, "removed": True}
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ModelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    category: str = Field(default="general", max_length=64)
    modalities: List[str] = Field(default=["text"], min_length=1, max_length=8)
    context_window: Optional[int] = Field(default=None, ge=1, le=100_000_000)
    is_local: bool = False
    is_active: bool = True
    source_type: str = Field(default="user", max_length=32)
    source_uri: str = Field(default="", max_length=1024)
    description: str = Field(default="", max_length=4000)


class ModelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    provider: Optional[str] = Field(default=None, min_length=1, max_length=64)
    category: Optional[str] = Field(default=None, max_length=64)
    modalities: Optional[List[str]] = Field(default=None, min_length=1, max_length=8)
    context_window: Optional[int] = Field(default=None, ge=1, le=100_000_000)
    is_local: Optional[bool] = None
    is_active: Optional[bool] = None
    source_type: Optional[str] = Field(default=None, max_length=32)
    source_uri: Optional[str] = Field(default=None, max_length=1024)
    description: Optional[str] = Field(default=None, max_length=4000)


@models_router.get("")
async def list_models(category: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(ModelRecord)
    if category and category != "all":
        stmt = stmt.where(ModelRecord.category == category)
    res = await db.execute(stmt)
    return [m.to_dict() for m in res.scalars().all()]


@models_router.post("")
async def create_model(request: ModelCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await model_lifecycle_service.create(db, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.patch("/{model_id}")
async def update_model(model_id: str, request: ModelUpdateRequest, db: AsyncSession = Depends(get_db)):
    values = request.model_dump(exclude_unset=True)
    revision = values.pop("expected_revision")
    try:
        return (await model_lifecycle_service.update(db, model_id, values, revision)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ModelCapabilityEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(max_length=64)
    supported: bool
    score: Optional[float] = Field(default=None, ge=0, le=100)
    provenance: str = Field(default="user_declared", max_length=32)
    source_type: str = Field(default="user", max_length=32)
    source_uri: str = Field(default="", max_length=1024)
    evidence: Dict[str, Any] = Field(default_factory=dict, max_length=50)
    observed_at: datetime
    expires_at: Optional[datetime] = None


@models_router.get("/{model_id}/capabilities")
async def get_model_capabilities(model_id: str, db: AsyncSession = Depends(get_db)):
    try:
        aggregate = await capability_evidence_service.aggregate(db, model_id)
        aggregate["evidence"] = [record.to_dict() for record in await capability_evidence_service.list(db, model_id)]
        return aggregate
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.post("/{model_id}/capabilities")
async def record_model_capability(model_id: str, request: ModelCapabilityEvidenceRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await capability_evidence_service.record(db, model_id, request.model_dump(), allowed_provenance={"user_declared"})).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ModelPriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    input_per_m: Optional[float] = Field(default=None, ge=0)
    output_per_m: Optional[float] = Field(default=None, ge=0)
    cache_per_m: Optional[float] = Field(default=None, ge=0)
    reasoning_per_m: Optional[float] = Field(default=None, ge=0)
    source_type: str = Field(max_length=32)
    source_uri: str = Field(default="", max_length=1024)
    provenance: str = Field(max_length=32)
    confidence: str = Field(default="unknown", max_length=16)
    effective_from: datetime
    effective_to: Optional[datetime] = None


@models_router.get("/{model_id}/prices")
async def list_model_prices(model_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await pricing_service.list(db, model_id)]


@models_router.post("/{model_id}/prices")
async def record_model_price(model_id: str, request: ModelPriceRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await pricing_service.record(db, model_id, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ModelAvailabilityObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(max_length=32)
    source: str = Field(max_length=32)
    evidence: Dict[str, Any] = Field(default_factory=dict, max_length=50)
    ttl_seconds: int = Field(default=300, ge=10, le=86400)


@models_router.post("/{model_id}/availability")
async def record_model_availability(model_id: str, request: ModelAvailabilityObservationRequest, db: AsyncSession = Depends(get_db)):
    try:
        record = await model_registry_service.record_observation(db, model_id, **request.model_dump())
        return record.to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.delete("/{model_id}")
async def archive_model(model_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return (await model_lifecycle_service.archive(db, model_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@models_router.patch("/{model_id}/toggle-active")
async def toggle_model_active(model_id: str, db: AsyncSession = Depends(get_db)):
    model = await db.get(ModelRecord, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.lifecycle_status == "archived":
        raise HTTPException(status_code=409, detail={"code": "model_archived", "message": "Archived models cannot be enabled."})
    model.is_active = not model.is_active
    model.revision = (model.revision or 0) + 1
    await db.commit()
    return {"id": model.id, "is_active": model.is_active}


@models_router.get("/baseline/status")
async def get_reference_baseline(db: AsyncSession = Depends(get_db)):
    return await baseline_service.current(db)


@models_router.patch("/{model_id}/set-baseline")
async def set_reference_baseline(model_id: str, db: AsyncSession = Depends(get_db)):
    try:
        model = await baseline_service.set(db, model_id)
        return {"status": "success", "baseline_model_id": model.id}
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


# --- Agents Router ---
agents_router = APIRouter(prefix="/api/agents", tags=["Agents"])
agent_lifecycle_service = AgentLifecycleService(system_scanner, secret_vault)


def _raise_agent_error(exc: AgentLifecycleError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@agents_router.get("")
async def list_agents(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AgentRecord))
    return [a.to_dict() for a in res.scalars().all()]


class AgentInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str = Field(min_length=1, max_length=1024)
    version_probe_args: List[str] = []
    timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)


@agents_router.post("/inspect")
async def inspect_agent(request: AgentInspectRequest):
    try:
        version_args = validate_probe_args(request.version_probe_args)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await system_scanner.inspect_manual(
        executable=request.executable,
        version_args=version_args,
        timeout_seconds=request.timeout_seconds,
    )


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    executable: str = Field(min_length=1, max_length=1024)
    version_probe_args: List[str] = []
    health_probe_args: List[str] = []
    invocation_args: List[str] = ["{prompt}"]
    input_method: str = "argument"
    output_method: str = "stdout"
    working_directory: str = "workspace"
    supports_pty: bool = False
    supports_interactive: bool = False
    capabilities: List[str] = []
    environment_refs: List[str] = []
    probe_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
    permission_profile: str = "developer"
    auth_required: bool = False
    auth_method: str = "none"
    auth_setup_instructions: str = Field(default="", max_length=1000)
    description: str = ""


@agents_router.post("")
async def add_agent(agent: AgentCreate, db: AsyncSession = Depends(get_db)):
    try:
        record = await agent_lifecycle_service.create(db, agent.model_dump())
        return record.to_dict()
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    executable: Optional[str] = Field(default=None, min_length=1, max_length=1024)
    version_probe_args: Optional[List[str]] = None
    health_probe_args: Optional[List[str]] = None
    invocation_args: Optional[List[str]] = None
    input_method: Optional[str] = None
    output_method: Optional[str] = None
    working_directory: Optional[str] = None
    supports_pty: Optional[bool] = None
    supports_interactive: Optional[bool] = None
    capabilities: Optional[List[str]] = None
    environment_refs: Optional[List[str]] = None
    probe_timeout_seconds: Optional[float] = Field(default=None, ge=0.1, le=30)
    permission_profile: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=4000)
    auth_required: Optional[bool] = None
    auth_method: Optional[str] = None
    auth_setup_instructions: Optional[str] = Field(default=None, max_length=1000)
    user_enabled: Optional[bool] = None


@agents_router.patch("/{agent_id}")
async def update_agent(agent_id: str, update_request: AgentUpdate, db: AsyncSession = Depends(get_db)):
    try:
        values = update_request.model_dump(exclude_unset=True)
        expected_revision = values.pop("expected_revision")
        record = await agent_lifecycle_service.update(db, agent_id, values, expected_revision)
        return record.to_dict()
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


@agents_router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_lifecycle_service.remove(db, agent_id)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


class AgentSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=16384)


@agents_router.get("/{agent_id}/secrets")
async def list_agent_secrets(agent_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_lifecycle_service.list_secrets(db, agent_id)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


@agents_router.put("/{agent_id}/secrets")
async def set_agent_secret(agent_id: str, request: AgentSecretRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_lifecycle_service.set_secret(db, agent_id, request.reference, request.value)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


@agents_router.delete("/{agent_id}/secrets/{reference}")
async def delete_agent_secret(agent_id: str, reference: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_lifecycle_service.delete_secret(db, agent_id, reference)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


@agents_router.post("/{agent_id}/auth/check")
async def check_agent_auth(agent_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_lifecycle_service.check_auth(db, agent_id)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


@agents_router.post("/{agent_id}/rescan")
async def rescan_agent(agent_id: str):
    try:
        return await agent_lifecycle_service.rescan(agent_id)
    except AgentLifecycleError as exc:
        _raise_agent_error(exc)


# --- Scanner Router ---
scanner_router = APIRouter(prefix="/api/scanner", tags=["Scanner"])


@scanner_router.post("/detect")
async def trigger_scan():
    return await system_scanner.scan_system()


@scanner_router.get("/adapters")
async def list_discovery_adapters():
    return [
        {
            "id": adapter.adapter_id,
            "name": adapter.display_name,
            "kind": adapter.kind.value,
            "executables": list(adapter.executable_names),
            "capabilities": list(adapter.capabilities),
            "source": adapter.source,
        }
        for adapter in system_scanner.adapters
    ]


# --- Router Playground Router ---
router_router = APIRouter(prefix="/api/router", tags=["Router"])


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=262144)
    mode: str = Field(default="balanced", max_length=32)
    custom_weights: Optional[Dict[str, float]] = None


@router_router.post("/recommend")
async def get_routing_recommendation(req: RecommendRequest):
    return await model_router.recommend_model(
        prompt=req.prompt,
        mode=req.mode,
        custom_weights=req.custom_weights,
    )


# --- Task Execution & Runs Router ---
task_router = APIRouter(prefix="/api/tasks", tags=["Tasks"])
runs_router = APIRouter(prefix="/api/runs", tags=["Runs"])


# --- Approved Workspaces Router ---
workspace_router = APIRouter(prefix="/api/workspaces", tags=["Workspaces"])
projects_router = APIRouter(prefix="/api/projects", tags=["Projects"])
assets_router = APIRouter(prefix="/api/assets", tags=["Assets"])
asset_library_router = APIRouter(prefix="/api/asset-library", tags=["Asset Library"])
orchestrations_router = APIRouter(prefix="/api/orchestrations", tags=["Orchestrations"])
search_router = APIRouter(prefix="/api/search", tags=["Search"])


@search_router.get("")
async def global_search(q: str = Query(min_length=2, max_length=200), project_id: Optional[str] = None, limit: int = Query(default=20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    term = f"%{q.lower()}%"
    results = []
    projects = (await db.execute(select(ProjectRecord).where(func.lower(ProjectRecord.name).like(term) | func.lower(ProjectRecord.purpose).like(term)).limit(limit))).scalars().all()
    results.extend({"type": "project", "id": item.id, "project_id": item.id, "title": item.name, "detail": item.project_type} for item in projects if not project_id or item.id == project_id)
    requirement_query = select(ProjectRequirementRecord).where(func.lower(ProjectRequirementRecord.title).like(term) | func.lower(ProjectRequirementRecord.description).like(term))
    task_query = select(OrchestrationTaskRecord).where(func.lower(OrchestrationTaskRecord.title).like(term) | func.lower(OrchestrationTaskRecord.description).like(term))
    asset_query = select(AssetRecord).where(func.lower(AssetRecord.relative_path).like(term))
    decision_query = select(ProjectDecisionRecord).where(func.lower(ProjectDecisionRecord.statement).like(term) | func.lower(ProjectDecisionRecord.rationale).like(term))
    run_query = select(TaskRun).where(func.lower(TaskRun.prompt).like(term))
    if project_id:
        requirement_query = requirement_query.where(ProjectRequirementRecord.project_id == project_id)
        task_query = task_query.where(OrchestrationTaskRecord.project_id == project_id)
        asset_query = asset_query.where(AssetRecord.project_id == project_id)
        decision_query = decision_query.where(ProjectDecisionRecord.project_id == project_id)
        run_query = run_query.where(TaskRun.project_id == project_id)
    for kind, statement, mapper in [
        ("requirement", requirement_query, lambda item: (item.project_id, item.title, item.status)),
        ("task", task_query, lambda item: (item.project_id, item.title, item.state)),
        ("asset", asset_query, lambda item: (item.project_id, item.relative_path, item.asset_type or "unknown")),
        ("decision", decision_query, lambda item: (item.project_id, item.statement, item.status)),
        ("run", run_query, lambda item: (item.project_id, item.prompt, item.status)),
    ]:
        rows = (await db.execute(statement.limit(limit))).scalars().all()
        for item in rows:
            scope, title, detail = mapper(item)
            results.append({"type": kind, "id": item.id, "project_id": scope, "title": title, "detail": detail})
    agents = (await db.execute(select(AgentRecord).where(func.lower(AgentRecord.name).like(term)).limit(limit))).scalars().all()
    results.extend({"type": "agent", "id": item.id, "project_id": None, "title": item.name, "detail": item.status} for item in agents)
    return {"query": q, "project_id": project_id, "results": results[:limit], "content_searched": False, "secrets_searched": False}


class OrchestrationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=64)


class OrchestrationCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Dict[str, Any] = Field(default_factory=dict, max_length=100)


class OrchestrationDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(min_length=1, max_length=64)
    # Absent, the dispatcher derives the pack budget from the selected route's own
    # declared context window. A stated value is a deliberate ceiling on the pack and
    # is honoured verbatim; the fixed default this replaced was a number about no
    # route in particular, and it vetoed every repair dispatch whose scope outgrew it.
    token_limit: Optional[int] = Field(default=None, ge=128, le=2_000_000)
    timeout_seconds: Optional[float] = Field(default=None, ge=1, le=3600)
    max_tasks: int = Field(default=1, ge=1, le=16)


@orchestrations_router.post("")
async def create_orchestration(request: OrchestrationCreateRequest, db: AsyncSession = Depends(get_db)):
    return (await orchestration_command_service.create(db, request.project_id)).to_dict()


@orchestrations_router.get("/{orchestration_id}")
async def get_orchestration(orchestration_id: str, db: AsyncSession = Depends(get_db)):
    record = await db.get(OrchestrationCheckpointRecord, orchestration_id)
    if not record:
        raise HTTPException(status_code=404, detail={"code": "orchestration_not_found", "message": "Orchestration was not found."})
    return record.to_dict()


@orchestrations_router.post("/{orchestration_id}/dispatch")
async def dispatch_orchestration(orchestration_id: str, request: OrchestrationDispatchRequest, db: AsyncSession = Depends(get_db)):
    checkpoint = await db.get(OrchestrationCheckpointRecord, orchestration_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail={"code": "orchestration_not_found", "message": "Orchestration was not found."})
    try:
        return await ProjectDispatcherService(process_manager).dispatch_ready(db, checkpoint.project_id, request.workspace_id, orchestration_id, request.token_limit, request.timeout_seconds, request.max_tasks)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@orchestrations_router.post("/{orchestration_id}/cancel-executions")
async def cancel_orchestration_executions(orchestration_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await ProjectDispatcherService(process_manager).cancel(db, orchestration_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@orchestrations_router.post("/{orchestration_id}/reconcile-completeness")
async def reconcile_orchestration_completeness(orchestration_id: str, request: OrchestrationDispatchRequest, db: AsyncSession = Depends(get_db)):
    checkpoint = await db.get(OrchestrationCheckpointRecord, orchestration_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail={"code": "orchestration_not_found", "message": "Orchestration was not found."})
    try:
        # Use the reconciliation service from the dispatcher
        dispatcher = ProjectDispatcherService(process_manager)
        return await dispatcher.reconciliation.reconcile(db, checkpoint.project_id, request.workspace_id, orchestration_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@orchestrations_router.post("/{orchestration_id}/{action}")
async def command_orchestration(orchestration_id: str, action: str, request: OrchestrationCommandRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await orchestration_command_service.command(db, orchestration_id, action, request.payload)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@assets_router.get("")
async def list_assets(project_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    statement = select(AssetRecord)
    if project_id:
        statement = statement.where(AssetRecord.project_id == project_id)
    assets = (await db.execute(statement.order_by(AssetRecord.created_at.desc(), AssetRecord.id))).scalars().all()
    return [asset.to_dict() for asset in assets]


media_transform_service = MediaTransformService(process_manager)


class MediaTransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_path: str = Field(min_length=1, max_length=1024)
    parameters: Dict[str, Any] = Field(default_factory=dict, max_length=20)
    timeout_seconds: float = Field(default=120, ge=1, le=1800)
    execution_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


@assets_router.get("/transforms/capability")
async def media_transform_capability():
    return media_transform_service.capability()


@assets_router.post("/{asset_id}/transform/{kind}")
async def transform_asset(asset_id: str, kind: str, request: MediaTransformRequest, db: AsyncSession = Depends(get_db)):
    try:
        if kind == "image":
            return await media_transform_service.image(db, asset_id, request.output_path, request.parameters, request.timeout_seconds, request.execution_id)
        if kind == "audio":
            return await media_transform_service.audio(db, asset_id, request.output_path, request.parameters, request.timeout_seconds, request.execution_id)
        if kind == "waveform":
            return await media_transform_service.waveform(db, asset_id, request.output_path, request.parameters, request.timeout_seconds, request.execution_id)
        raise DomainError("validation_failed", message="Media transform kind is unsupported.")
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@assets_router.post("/transforms/{execution_id}/cancel")
async def cancel_media_transform(execution_id: str):
    return {"execution_id": execution_id, "cancelled": await process_manager.cancel(execution_id)}


@assets_router.get("/{asset_id}")
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await db.get(AssetRecord, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "asset_not_found", "message": "Asset was not found."})
    usage = (await db.execute(select(AssetUsageRecord).where(AssetUsageRecord.asset_id == asset_id).order_by(AssetUsageRecord.created_at))).scalars().all()
    variants = (await db.execute(select(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id == asset_id).order_by(AssetTransformJobRecord.created_at))).scalars().all()
    return {**asset.to_dict(), "usage": [item.to_dict() for item in usage], "variants": [item.to_dict() for item in variants], "validation": await asset_validation_service.validate(db, asset_id)}


@asset_library_router.get("")
async def list_asset_collections(project_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await asset_library_service.list(db, project_id)


@projects_router.get("/{project_id}/value")
async def get_project_value(project_id: str, start: datetime, end: datetime, hours_per_defect: float = Query(default=1, ge=0, le=1000), hourly_value: float = Query(default=0, ge=0, le=1000000), db: AsyncSession = Depends(get_db)):
    analytics = await analytics_service.aggregate(db, start, end, project_id)
    automation = await automation_value_service.aggregate(db, project_id)
    needs = await needs_value_service.aggregate(db, project_id)
    quality = await quality_workspace_service.summary(db, project_id)
    rework = rework_value_service.calculate([*quality["blocking_findings"], *quality["advisory_findings"]], {"hours_per_defect": hours_per_defect, "hourly_value": hourly_value})
    return {"project_id": project_id, "period": analytics["range"], "financials": analytics["financials"], "automation": automation, "needs": needs, "qa_rework": rework, "mixed_total": None, "provenance_groups": ["provider_reported", "measured", "estimated", "unknown"]}


@projects_router.get("/{project_id}/plan")
async def get_project_plan(project_id: str, db: AsyncSession = Depends(get_db)):
    orchestrations = (await db.execute(select(OrchestrationCheckpointRecord).where(OrchestrationCheckpointRecord.project_id == project_id).order_by(OrchestrationCheckpointRecord.updated_at.desc()))).scalars().all()
    tasks = (await db.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id).order_by(OrchestrationTaskRecord.created_at))).scalars().all()
    needs = (await db.execute(select(ProjectNeedRecord).where(ProjectNeedRecord.project_id == project_id).order_by(ProjectNeedRecord.created_at))).scalars().all()
    approvals = [item.to_dict() for item in await approval_service.list(db) if item.scope_type == "orchestration" and any(item.scope_id == orchestration.id for orchestration in orchestrations)]
    return {"project_id": project_id, "orchestrations": [item.to_dict() for item in orchestrations], "tasks": [item.to_dict() for item in tasks], "needs": [item.to_dict() for item in needs], "approvals": approvals}


CAPABILITY_LABELS = {"coding": "Coding capability", "research": "Research capability", "reasoning": "Reasoning capability", "general": "General assistant capability", "image": "Image capability", "arabic": "Arabic language capability"}


def _capability_blockers(required: List[str], preflight: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lead with the capability the project needs, not with the brands that lack it.

    The preflight names every route that is not usable, which is the right technical
    record but the wrong first sentence for an owner: it reads as six unrelated tool
    failures rather than one missing capability. The route-level detail is preserved
    underneath so nothing is hidden.
    """
    raw = preflight.get("blockers") or []
    if not raw:
        return []
    labels = [CAPABILITY_LABELS.get(item, f"{item.replace('_', ' ').capitalize()} capability") for item in required] or ["Execution capability"]
    signin = [item for item in raw if item.get("code") in {"agent_auth_unverified", "provider_not_configured"}]
    host = [item for item in raw if item.get("code") == "host_capacity_unavailable"]
    if host:
        return [*host, *[item for item in raw if item not in host]]
    if signin and len(signin) == len(raw):
        return [{
            "code": "capability_signin_required",
            "title": f"{labels[0]} required",
            "detail": "Sign in to a coding tool TEMM already found on this computer, then check readiness again." if "coding" in required else "Connect an execution account or sign in to a detected local tool, then check readiness again.",
            "action_target": "fleet",
            "required_capabilities": required,
            "routes": raw,
        }]
    return [{
        "code": "capability_unavailable",
        "title": f"{labels[0]} required",
        "detail": "No connected executor currently has evidence for this capability.",
        "action_target": "fleet",
        "required_capabilities": required,
        "routes": raw,
    }, *[item for item in raw if item.get("code") not in {"agent_auth_unverified", "provider_not_configured"}]]


@projects_router.get("/{project_id}/execution-readiness")
async def get_project_execution_readiness(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(ProjectRecord, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Project was not found."})
    links = await project_workspace_service.list(db, project_id)
    primary = next((item for item in links if item["role"] == "primary" and item.get("workspace")), None)
    tasks = (await db.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == project_id).order_by(OrchestrationTaskRecord.created_at))).scalars().all()
    next_task = next((item for item in tasks if item.state in {"planned", "ready", "blocked", "failed"}), None)
    required = [item for item in (next_task.to_dict().get("executor_needs", {}).get("capabilities", []) if next_task else []) if isinstance(item, str) and item.strip()]
    if not primary:
        return {"project_id": project_id, "ready": False, "workspace": None, "task_id": next_task.id if next_task else None, "required_capabilities": required, "blockers": [{"code": "workspace_required", "title": "Project folder required", "detail": "Connect an approved project folder before TEMM can change files.", "action_target": "project_workspace"}]}
    workspace = primary["workspace"]
    prompt = next_task.description if next_task and next_task.description else project.purpose
    preflight = await build_execution_preflight(prompt=prompt or "Project work", workspace_id=workspace["id"], required_capabilities=required or None)
    return {"project_id": project_id, "ready": preflight["can_execute"], "workspace": workspace, "workspace_role": primary["role"], "task_id": next_task.id if next_task else None, "required_capabilities": preflight["required_capabilities"], "capability_basis": preflight["capability_basis"], "preflight": preflight, "blockers": _capability_blockers(preflight["required_capabilities"], preflight)}


@projects_router.post("/{project_id}/plan/compile")
async def compile_project_plan(project_id: str, request: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    proposal_id = request.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "message": "An approved blueprint proposal is required."})
    try:
        return await plan_compiler_service.compile(db, project_id, proposal_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.get("/{project_id}/completion")
async def get_project_completion(project_id: str, db: AsyncSession = Depends(get_db)):
    return await completion_assessment_service.assess(db, project_id)


@projects_router.get("/{project_id}/deliverables")
async def list_project_deliverables(project_id: str, db: AsyncSession = Depends(get_db)):
    records = (await db.execute(select(DeliverableRecord).where(DeliverableRecord.project_id == project_id).order_by(DeliverableRecord.created_at.desc()))).scalars().all()
    return [record.to_dict() for record in records]


class CreateDeliverableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    relative_paths: List[str] = Field(min_length=1, max_length=5000)


@projects_router.post("/{project_id}/deliverables/package")
async def create_project_deliverable(project_id: str, request: CreateDeliverableRequest, db: AsyncSession = Depends(get_db)):
    """Package project files into a reproducible deliverable with integrity evidence."""
    project = await db.get(ProjectRecord, project_id)
    workspace = await db.get(WorkspaceRecord, request.workspace_id)
    if not project or project.lifecycle_status != "active":
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Active project was not found."})
    if not workspace:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "Workspace was not found."})
    from ..services.packaging import PackagingService
    from ..services.completion_assessment import CompletionAssessmentService
    try:
        assessment = await CompletionAssessmentService().assess(db, project_id)
        package_result = PackagingService().package(workspace.path, request.relative_paths)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    record = DeliverableRecord(
        id=f"deliverable-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        workspace_id=workspace.id,
        name=request.name,
        version=request.version,
        relative_path=f"deliverables/{request.name}-{request.version}.zip",
        checksum=package_result["archive_sha256"],
        readiness="ready" if assessment["ready"] else "blocked",
        requirement_ids_json=json.dumps([b["requirement_id"] for b in assessment["blockers"].get("requirements", [])]),
        asset_ids_json="[]",
        run_ids_json="[]",
        gate_ids_json="[]",
    )
    db.add(record)
    await db.commit()
    # Store archive in workspace for download
    from pathlib import Path
    deliverable_dir = Path(workspace.path) / "deliverables"
    deliverable_dir.mkdir(parents=True, exist_ok=True)
    archive_path = deliverable_dir / f"{request.name}-{request.version}.zip"
    archive_path.write_bytes(package_result["archive"])
    return {**record.to_dict(), "assessment": {"ready": assessment["ready"], "blocker_count": sum(len(v) for v in assessment["blockers"].values() if isinstance(v, list))}, "archive_size": len(package_result["archive"]), "manifest": package_result["manifest"], "download_path": f"/api/projects/{project_id}/deliverables/{record.id}/download"}


@projects_router.get("/{project_id}/deliverables/{deliverable_id}/download")
async def download_deliverable(project_id: str, deliverable_id: str, db: AsyncSession = Depends(get_db)):
    """Download a packaged deliverable archive."""
    record = await db.get(DeliverableRecord, deliverable_id)
    if not record or record.project_id != project_id:
        raise HTTPException(status_code=404, detail={"code": "deliverable_not_found", "message": "Deliverable was not found."})
    workspace = await db.get(WorkspaceRecord, record.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "Workspace was not found."})
    from pathlib import Path
    archive_path = Path(workspace.path) / record.relative_path
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail={"code": "archive_not_found", "message": "Archive file is not available."})
    return Response(content=archive_path.read_bytes(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{record.name}-{record.version}.zip"', "X-Checksum-SHA256": record.checksum})


@projects_router.get("/{project_id}/research")
async def get_project_research(project_id: str, db: AsyncSession = Depends(get_db)):
    queries = (await db.execute(select(ResearchQueryRecord).where(ResearchQueryRecord.project_id == project_id).order_by(ResearchQueryRecord.created_at.desc()))).scalars().all()
    result = []
    for query in queries:
        sources = (await db.execute(select(ResearchSourceRecord).where(ResearchSourceRecord.query_id == query.id).order_by(ResearchSourceRecord.url, ResearchSourceRecord.version.desc()))).scalars().all()
        claims = (await db.execute(select(ResearchClaimRecord).where(ResearchClaimRecord.query_id == query.id).order_by(ResearchClaimRecord.created_at))).scalars().all()
        claim_payload = []
        for claim in claims:
            citations = (await db.execute(select(ResearchCitationRecord).where(ResearchCitationRecord.claim_id == claim.id).order_by(ResearchCitationRecord.created_at))).scalars().all()
            claim_payload.append({**claim.to_dict(), "citations": [item.to_dict() for item in citations]})
        result.append({**query.to_dict(), "sources": [item.to_dict() for item in sources], "claims": claim_payload})
    return result


@projects_router.get("/{project_id}/quality")
async def get_project_quality(project_id: str, db: AsyncSession = Depends(get_db)):
    return await quality_workspace_service.summary(db, project_id)


@projects_router.get("/{project_id}/context-packs")
async def list_project_context_packs(project_id: str, db: AsyncSession = Depends(get_db)):
    return [context_pack_service.inspect(record) for record in await context_pack_service.list(db, project_id)]


class BlueprintProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: Dict[str, Any]


@projects_router.post("/{project_id}/blueprints/from-goal")
async def create_blueprint_from_goal(project_id: str, request: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    project = await db.get(ProjectRecord, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "Project was not found."})
    goal = str(request.get("goal") or project.purpose or "").strip()
    if not goal:
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "message": "A project goal is required before creating a blueprint."})
    template = WEBSITE_TEMPLATE if project.project_type == "website" else BUSINESS_SYSTEM_TEMPLATE if project.project_type == "business_system" else WEBSITE_TEMPLATE
    proposal = {
        "template_id": template.template_id,
        "template_version": template.version,
        "goal": goal,
        "requirements": [{
            "proposal_id": f"goal-{uuid.uuid4().hex[:12]}",
            "section_id": section.section_id,
            "title": section.title,
            "description": f"Deliver the {section.title.lower()} needed to accomplish the project goal.",
            "requirement_type": section.requirement_types[0],
            "priority": "must",
            "acceptance": [{"statement": gate.description} for gate in section.gates] or [{"statement": f"Evidence confirms the {section.title.lower()} is complete."}],
            "truth_state": "proposed", "status": "proposed", "provenance": "template_proposed", "approved": False,
        } for section in template.sections],
        "questions": [{"question_id": question.question_id, "section_id": section.section_id, "text": question.text, "required": question.required, "status": "proposed", "provenance": "template_proposed"} for section in template.sections for question in section.questions],
        "approval_required": True,
        "implementation_started": False,
        "source": "goal_template",
    }
    exact_match = re.search(r"(?:file|artifact)\s+(?:named|called)\s+([A-Za-z0-9._/-]+)\s+(?:with|containing)\s+(?:exact\s+content\s+)?[\"']?([^\"']+)[\"']?", goal, re.IGNORECASE)
    if exact_match and proposal["requirements"]:
        path, content = exact_match.group(1), exact_match.group(2).strip()
        proof = proposal["requirements"][0]
        proof.update({"title": f"Create {path}", "description": f"Create only {path} containing exactly {content}.", "acceptance": [{"statement": f"{path} contains the requested content.", "evaluator": {"type": "file_exact_content", "path": path, "content": content}}]})
        proposal["requirements"] = [proof]
        proposal["questions"] = []
    try:
        return (await blueprint_approval_service.create(db, project_id, proposal)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class BlueprintProposalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    content: Dict[str, Any]


class BlueprintProposalApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=128)


@projects_router.get("/{project_id}/blueprints")
async def list_blueprint_proposals(project_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await blueprint_approval_service.list(db, project_id)]


@projects_router.post("/{project_id}/blueprints")
async def create_blueprint_proposal(project_id: str, request: BlueprintProposalCreateRequest, db: AsyncSession = Depends(get_db)):
    try: return (await blueprint_approval_service.create(db, project_id, request.proposal)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.patch("/blueprints/{proposal_id}")
async def edit_blueprint_proposal(proposal_id: str, request: BlueprintProposalEditRequest, db: AsyncSession = Depends(get_db)):
    try: return (await blueprint_approval_service.edit(db, proposal_id, request.content, request.expected_revision)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/blueprints/{proposal_id}/approve")
async def approve_blueprint_proposal(proposal_id: str, request: BlueprintProposalApproveRequest, db: AsyncSession = Depends(get_db)):
    try: return await blueprint_approval_service.approve(db, proposal_id, request.actor, request.expected_revision)
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ProjectRequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=10000)
    requirement_type: str = Field(max_length=32)
    source_type: str = Field(max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=128)
    truth_state: str = Field(max_length=32)
    priority: str = Field(max_length=16)
    acceptance: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    owner: Optional[str] = Field(default=None, max_length=128)


class ProjectRequirementTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=32)
    actor: str = Field(min_length=1, max_length=128)
    rationale: str = Field(default="", max_length=10000)


class ProjectRequirementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=10000)
    priority: Optional[str] = Field(default=None, max_length=16)
    owner: Optional[str] = Field(default=None, max_length=128)
    truth_state: Optional[str] = Field(default=None, max_length=32)
    acceptance: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=100)
    evidence: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=100)


@projects_router.get("/{project_id}/requirements/view")
async def view_project_requirements(project_id: str, db: AsyncSession = Depends(get_db)):
    requirements = await requirement_service.list(db, project_id)
    edges = await requirement_graph_service.list(db, project_id)
    items = []
    for requirement in requirements:
        items.append({**requirement.to_dict(), "readiness": await requirement_readiness_service.derive(db, requirement.id), "impact": await requirement_graph_service.impact(db, requirement.id)})
    return {"project_id": project_id, "requirements": items, "edges": [edge.to_dict() for edge in edges]}


@projects_router.get("/{project_id}/requirements")
async def list_project_requirements(project_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await requirement_service.list(db, project_id)]


@projects_router.post("/{project_id}/requirements")
async def create_project_requirement(project_id: str, request: ProjectRequirementRequest, db: AsyncSession = Depends(get_db)):
    try: return (await requirement_service.create(db, project_id, request.model_dump())).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/requirements/{requirement_id}/transition")
async def transition_project_requirement(requirement_id: str, request: ProjectRequirementTransitionRequest, db: AsyncSession = Depends(get_db)):
    try: return (await requirement_service.transition(db, requirement_id, request.target, request.actor, request.rationale)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.patch("/requirements/{requirement_id}")
async def update_project_requirement(requirement_id: str, request: ProjectRequirementUpdateRequest, db: AsyncSession = Depends(get_db)):
    # Revision-checked edits reach the requirement service, which snapshots every
    # change. Without this route an approved requirement's acceptance could never be
    # refined through the API, so a prose-only contract could not be made verifiable.
    changes = {key: value for key, value in request.model_dump(exclude={"expected_revision"}).items() if value is not None}
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "message": "Requirement update requires at least one field."})
    try: return (await requirement_service.update(db, requirement_id, changes, request.expected_revision)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ProjectDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: str = Field(max_length=32)
    scope_id: Optional[str] = Field(default=None, max_length=128)
    statement: str = Field(min_length=1, max_length=10000)
    rationale: str = Field(min_length=1, max_length=10000)
    impact: str = Field(min_length=1, max_length=10000)
    rule: Dict[str, Any] = Field(default_factory=dict, max_length=100)
    source_type: str = Field(max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=128)
    supersedes_id: Optional[str] = Field(default=None, max_length=64)


class ProjectDecisionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(min_length=1, max_length=128)


@projects_router.get("/{project_id}/decisions")
async def list_project_decisions(project_id: str, status: Optional[str] = None, scope_type: Optional[str] = None, scope_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await decision_service.list(db, project_id, status, scope_type, scope_id)]


@projects_router.post("/{project_id}/decisions")
async def create_project_decision(project_id: str, request: ProjectDecisionRequest, db: AsyncSession = Depends(get_db)):
    values = request.model_dump(); supersedes_id = values.pop("supersedes_id")
    try: return (await decision_service.create(db, project_id, values, supersedes_id)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/decisions/{decision_id}/approve")
async def approve_project_decision(decision_id: str, request: ProjectDecisionActionRequest, db: AsyncSession = Depends(get_db)):
    try: return (await decision_service.decide(db, decision_id, "approve", request.actor)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/decisions/{decision_id}/reject")
async def reject_project_decision(decision_id: str, request: ProjectDecisionActionRequest, db: AsyncSession = Depends(get_db)):
    try: return (await decision_service.decide(db, decision_id, "reject", request.actor)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ProjectBrainFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: str = Field(max_length=64)
    fact_key: str = Field(min_length=2, max_length=128)
    value: Any = None
    truth_state: str = Field(max_length=32)
    provenance: str = Field(max_length=32)
    source_type: str = Field(max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=128)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    expected_revision: Optional[int] = Field(default=None, ge=1)


class ProjectBrainRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


@projects_router.get("/brain/facts/{fact_id}/revisions")
async def list_project_brain_revisions(fact_id: str, db: AsyncSession = Depends(get_db)):
    try: return await project_brain_service.revisions(db, fact_id)
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.get("/brain/facts/{fact_id}/diff")
async def diff_project_brain_revisions(fact_id: str, from_revision: int = Query(ge=1), to_revision: int = Query(ge=1), db: AsyncSession = Depends(get_db)):
    try: return await project_brain_service.diff(db, fact_id, from_revision, to_revision)
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/brain/facts/{fact_id}/restore")
async def restore_project_brain_revision(fact_id: str, request: ProjectBrainRestoreRequest, db: AsyncSession = Depends(get_db)):
    try: return (await project_brain_service.restore(db, fact_id, request.revision, request.expected_revision)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.get("/{project_id}/brain")
async def list_project_brain(project_id: str, section: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    try: return [record.to_dict() for record in await project_brain_service.list(db, project_id, section)]
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.put("/{project_id}/brain/facts")
async def merge_project_brain_fact(project_id: str, request: ProjectBrainFactRequest, db: AsyncSession = Depends(get_db)):
    values = request.model_dump(); revision = values.pop("expected_revision")
    try: return (await project_brain_service.merge(db, project_id, values, revision)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ProjectWorkspaceBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(min_length=1, max_length=64)
    role: str = Field(default="secondary", max_length=32)


@projects_router.get("/{project_id}/workspaces")
async def list_project_workspaces(project_id: str, db: AsyncSession = Depends(get_db)):
    try: return await project_workspace_service.list(db, project_id)
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/{project_id}/workspaces")
async def bind_project_workspace(project_id: str, request: ProjectWorkspaceBindRequest, db: AsyncSession = Depends(get_db)):
    try: return (await project_workspace_service.bind(db, project_id, request.workspace_id, request.role)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.delete("/{project_id}/workspaces/{workspace_id}")
async def unbind_project_workspace(project_id: str, workspace_id: str, db: AsyncSession = Depends(get_db)):
    try: await project_workspace_service.unbind(db, project_id, workspace_id); return {"project_id": project_id, "workspace_id": workspace_id, "removed": True}
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=128)
    purpose: str = Field(min_length=1, max_length=10000)
    project_type: str = Field(default="software", max_length=64)
    owner: str = Field(default="local_owner", min_length=1, max_length=128)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=128)
    purpose: Optional[str] = Field(default=None, max_length=10000)
    project_type: Optional[str] = Field(default=None, max_length=64)
    owner: Optional[str] = Field(default=None, min_length=1, max_length=128)


@projects_router.get("")
async def list_projects(include_archived: bool = False, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await project_service.list(db, include_archived)]


@projects_router.post("")
async def create_project(request: ProjectCreateRequest, db: AsyncSession = Depends(get_db)):
    try: return (await project_service.create(db, request.model_dump())).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.patch("/{project_id}")
async def update_project(project_id: str, request: ProjectUpdateRequest, db: AsyncSession = Depends(get_db)):
    values = request.model_dump(exclude_unset=True); revision = values.pop("expected_revision")
    try: return (await project_service.update(db, project_id, values, revision)).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/{project_id}/archive")
async def archive_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try: return (await project_service.transition(db, project_id, "archived")).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.post("/{project_id}/restore")
async def restore_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try: return (await project_service.transition(db, project_id, "active")).to_dict()
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@projects_router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try: await project_service.delete(db, project_id)
    except DomainError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


# --- Local Plugin Registry Router ---
plugins_router = APIRouter(prefix="/api/plugins", tags=["Plugins"])
plugin_runtime_service = PluginRuntimeService(process_manager)
plugin_conformance_service = PluginConformanceService(plugin_runtime_service)


async def _fetch_marketplace_bytes(url: str, policy):
    async with httpx.AsyncClient(follow_redirects=False, timeout=policy.timeout_seconds) as client:
        response = await client.get(url)
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Marketplace redirects are not followed automatically.")
        content = response.content
        if len(content) > policy.max_bytes:
            raise ValueError("Marketplace response exceeded size limit.")
        return {"content": content, "content_type": response.headers.get("content-type", ""), "content_length": len(content), "redirect_chain": [url]}


async def _fetch_marketplace_json(url: str, policy):
    response = await _fetch_marketplace_bytes(url, policy)
    response["json"] = json.loads(response["content"].decode("utf-8"))
    return response


plugin_marketplace_service = PluginMarketplaceService(Path.home() / ".ai_fleet" / "marketplace" / "plugins", url_safety_service, _fetch_marketplace_json, _fetch_marketplace_bytes)


class PluginPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_path: str = Field(min_length=1, max_length=1024)


class PluginRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_path: str = Field(min_length=1, max_length=1024)
    permission_profile: str = Field(default="safe", max_length=32)
    granted_permissions: List[str] = Field(default_factory=list, max_length=16)


class CatalogSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    index_url: str = Field(min_length=8, max_length=1024)
    public_key: str = Field(min_length=40, max_length=128)


class CatalogSourceStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MarketplaceInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=2, max_length=128)
    plugin_id: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=5, max_length=64)
    granted_permissions: List[str] = Field(default_factory=list, max_length=16)
    permission_profile: str = Field(default="developer", max_length=32)
    approval_id: str = Field(min_length=1, max_length=128)


class MarketplaceRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str = Field(min_length=1, max_length=128)


class MarketplacePackImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=2, max_length=128)
    pack_id: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=5, max_length=64)
    approval_id: str = Field(min_length=1, max_length=128)


class MarketplaceWorkflowImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=2, max_length=128)
    template_id: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=5, max_length=64)
    approval_id: str = Field(min_length=1, max_length=128)


def _inspect_plugin_folder(folder_path: str) -> Dict[str, Any]:
    try:
        folder = path_policy.existing_directory(folder_path)
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manifest_path = next((candidate for candidate in [folder / "manifest.yaml", folder / "manifest.yml", folder / "manifest.json"] if candidate.exists()), None)
    if not manifest_path:
        raise HTTPException(status_code=400, detail="Plugin package needs manifest.yaml, manifest.yml, or manifest.json.")
    try:
        if manifest_path.suffix == ".json":
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse plugin manifest: {exc}") from exc
    try:
        parsed_manifest = PluginManifest.parse(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plugin_id = parsed_manifest.plugin_id
    permissions = [item.value for item in parsed_manifest.permissions]
    try:
        entrypoint_path = contained_entrypoint(folder, parsed_manifest.entrypoint)
        package_hash = hash_plugin_folder(folder)
    except PluginPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    checklist = {
        "manifest": True,
        "adapter": entrypoint_path.is_file(),
        "readme": any((folder / name).exists() for name in ["README.md", "readme.md"]),
        "tests": (folder / "tests").is_dir(),
    }
    return {
        "valid": checklist["manifest"] and checklist["adapter"],
        "folder_path": str(folder),
        "manifest_path": str(manifest_path),
        "manifest": parsed_manifest.to_dict(),
        "plugin_id": plugin_id,
        "name": parsed_manifest.name,
        "version": parsed_manifest.version,
        "protocol_version": parsed_manifest.protocol,
        "compatible": negotiate_protocol(parsed_manifest.protocol),
        "plugin_type": parsed_manifest.plugin_type.value,
        "permissions": permissions,
        "entrypoint": str(entrypoint_path),
        "package_hash": package_hash,
        "checklist": checklist,
        "executes_code": False,
    }


@plugins_router.get("")
async def list_plugins(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PluginRecord).order_by(PluginRecord.created_at.desc()))
    return [plugin.to_dict() for plugin in res.scalars().all()]


@plugins_router.get("/marketplace/sources")
async def list_marketplace_sources(db: AsyncSession = Depends(get_db)):
    records = (await db.execute(select(PluginCatalogSourceRecord).order_by(PluginCatalogSourceRecord.created_at))).scalars().all()
    return [record.to_dict() for record in records]


@plugins_router.post("/marketplace/sources")
async def add_marketplace_source(req: CatalogSourceRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.add_source(db, req.source_id, req.index_url, req.public_key)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.patch("/marketplace/sources/{source_id}")
async def set_marketplace_source_state(source_id: str, req: CatalogSourceStateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.set_source_enabled(db, source_id, req.enabled)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.delete("/marketplace/sources/{source_id}", status_code=204)
async def remove_marketplace_source(source_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await plugin_marketplace_service.remove_source(db, source_id)
        return Response(status_code=204)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.post("/marketplace/sources/{source_id}/refresh")
async def refresh_marketplace_source(source_id: str, db: AsyncSession = Depends(get_db)):
    try:
        platform_name = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
        return await plugin_marketplace_service.refresh(db, source_id, platform_name)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.get("/marketplace/catalog")
async def browse_marketplace(source_id: Optional[str] = Query(default=None, max_length=128), db: AsyncSession = Depends(get_db)):
    return await plugin_marketplace_service.browse(db, source_id, "plugin")


@plugins_router.get("/marketplace/benchmark-packs")
async def browse_marketplace_benchmark_packs(source_id: Optional[str] = Query(default=None, max_length=128), db: AsyncSession = Depends(get_db)):
    return await plugin_marketplace_service.browse(db, source_id, "benchmark_pack")


@plugins_router.post("/marketplace/benchmark-packs/import")
async def import_marketplace_benchmark_pack(req: MarketplacePackImportRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.import_benchmark_pack(db, req.source_id, req.pack_id, req.version, req.approval_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.get("/marketplace/workflow-templates")
async def browse_marketplace_workflow_templates(source_id: Optional[str] = Query(default=None, max_length=128), db: AsyncSession = Depends(get_db)):
    return await plugin_marketplace_service.browse(db, source_id, "workflow_template")


@plugins_router.post("/marketplace/workflow-templates/import")
async def import_marketplace_workflow_template(req: MarketplaceWorkflowImportRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.import_workflow_template(db, req.source_id, req.template_id, req.version, req.approval_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.get("/marketplace/workflow-templates/imported")
async def list_imported_workflow_templates(db: AsyncSession = Depends(get_db)):
    records = (await db.execute(select(WorkflowTemplateVersionRecord).order_by(WorkflowTemplateVersionRecord.created_at.desc()))).scalars().all()
    return [record.to_dict() for record in records]


@plugins_router.post("/marketplace/install")
async def install_marketplace_plugin(req: MarketplaceInstallRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.install(db, req.source_id, req.plugin_id, req.version, req.granted_permissions, req.permission_profile, req.approval_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.post("/marketplace/{plugin_id}/rollback")
async def rollback_marketplace_plugin(plugin_id: str, req: MarketplaceRemoveRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_marketplace_service.rollback(db, plugin_id, req.approval_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.post("/marketplace/{plugin_id}/remove", status_code=204)
async def remove_marketplace_plugin(plugin_id: str, req: MarketplaceRemoveRequest, db: AsyncSession = Depends(get_db)):
    try:
        await plugin_marketplace_service.remove(db, plugin_id, req.approval_id)
        return Response(status_code=204)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.post("/{plugin_id}/reload")
async def reload_plugin(plugin_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return (await plugin_runtime_service.reload(db, plugin_id)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@plugins_router.post("/{plugin_id}/conformance")
async def run_plugin_conformance(plugin_id: str, db: AsyncSession = Depends(get_db)):
    return await plugin_conformance_service.run(db, plugin_id)


@plugins_router.post("/inspect")
async def inspect_plugin(req: PluginPathRequest):
    return _inspect_plugin_folder(req.folder_path)


@plugins_router.post("/register")
async def register_plugin(req: PluginRegisterRequest, db: AsyncSession = Depends(get_db)):
    inspection = _inspect_plugin_folder(req.folder_path)
    if not inspection["valid"]:
        raise HTTPException(status_code=400, detail="Plugin package is missing adapter.py.")
    try:
        parsed_manifest = PluginManifest.parse(inspection["manifest"])
        plugin_permission_policy.enforce(parsed_manifest, req.permission_profile, req.granted_permissions)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    existing = await db.get(PluginRecord, inspection["plugin_id"])
    if existing:
        raise HTTPException(status_code=409, detail="A plugin with this id is already registered.")
    record = PluginRecord(
        id=inspection["plugin_id"],
        name=inspection["name"],
        path=inspection["folder_path"],
        version=inspection["version"],
        protocol_version=inspection["protocol_version"],
        plugin_type=inspection["plugin_type"],
        status="registered",
        manifest=json.dumps(inspection["manifest"]),
        permissions=json.dumps(inspection["permissions"]),
        granted_permissions=json.dumps(req.granted_permissions),
        permission_profile=req.permission_profile,
        package_hash=inspection["package_hash"],
        entrypoint=inspection["entrypoint"],
        load_state="eligible" if inspection["compatible"] else "incompatible",
    )
    db.add(record)
    await db.commit()
    return record.to_dict()


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    permission_profile: str = Field(default="developer", max_length=32)
    allowed_shells: List[str] = Field(default=["powershell"], max_length=4)
    is_default: bool = False


class WorkspaceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    permission_profile: Optional[str] = Field(default=None, max_length=32)
    allowed_shells: Optional[List[str]] = Field(default=None, max_length=4)
    is_default: Optional[bool] = None


@workspace_router.get("")
async def list_workspaces(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(WorkspaceRecord).order_by(WorkspaceRecord.is_default.desc(), WorkspaceRecord.created_at.asc()))
    return [workspace.to_dict() for workspace in res.scalars().all()]


@workspace_router.post("")
async def create_workspace(req: WorkspaceCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        workspace_path = path_policy.existing_directory(req.path)
    except PathPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.permission_profile not in {"safe", "developer", "full"}:
        raise HTTPException(status_code=400, detail="Unsupported permission profile.")
    allowed_shells = [shell for shell in req.allowed_shells if shell in {"powershell", "cmd"}]
    if not allowed_shells:
        allowed_shells = ["powershell"]

    existing = (await db.execute(select(WorkspaceRecord).where(WorkspaceRecord.path == str(workspace_path)))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="This folder is already registered as a workspace.")

    count = (await db.execute(select(WorkspaceRecord))).scalars().all()
    make_default = req.is_default or not count
    if make_default:
        await db.execute(update(WorkspaceRecord).values(is_default=False))
    record = WorkspaceRecord(
        id=f"workspace-{uuid.uuid4().hex[:8]}",
        name=req.name.strip() or workspace_path.name,
        path=str(workspace_path),
        permission_profile=req.permission_profile,
        allowed_shells=json.dumps(allowed_shells),
        is_default=make_default,
    )
    db.add(record)
    await db.commit()
    return record.to_dict()


@workspace_router.patch("/{workspace_id}")
async def update_workspace(workspace_id: str, req: WorkspaceUpdateRequest, db: AsyncSession = Depends(get_db)):
    workspace = await db.get(WorkspaceRecord, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if req.name is not None:
        workspace.name = req.name.strip() or workspace.name
    if req.permission_profile is not None:
        if req.permission_profile not in {"safe", "developer", "full"}:
            raise HTTPException(status_code=400, detail="Unsupported permission profile.")
        workspace.permission_profile = req.permission_profile
    if req.allowed_shells is not None:
        allowed_shells = [shell for shell in req.allowed_shells if shell in {"powershell", "cmd"}]
        workspace.allowed_shells = json.dumps(allowed_shells or ["powershell"])
    if req.is_default:
        await db.execute(update(WorkspaceRecord).values(is_default=False))
        workspace.is_default = True
    await db.commit()
    return workspace.to_dict()


@workspace_router.delete("/{workspace_id}")
async def remove_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    workspace = await db.get(WorkspaceRecord, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    await db.delete(workspace)
    await db.commit()
    return {"status": "removed", "workspace_id": workspace_id, "files_deleted": False}


class TaskRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    prompt: str = Field(min_length=1, max_length=262144)
    model_id: Optional[str] = Field(default=None, max_length=128)
    agent_id: Optional[str] = Field(default=None, max_length=64)
    routing_mode: str = Field(default="balanced", max_length=32)
    workspace_id: Optional[str] = Field(default=None, max_length=64)
    interactive: bool = False
    terminal_columns: int = Field(default=120, ge=20, le=500)
    terminal_rows: int = Field(default=30, ge=5, le=200)


async def _require_run(db: AsyncSession, run_id: str) -> TaskRun:
    run = await db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "Run was not found."})
    return run


@runs_router.get("/compare")
async def compare_runs(run_id: List[str] = Query(...), db: AsyncSession = Depends(get_db)):
    try:
        return await run_comparison_service.compare(db, run_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@runs_router.get("")
async def list_runs(response: Response, limit: int = Query(default=50, ge=1, le=100), after: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    statement = select(TaskRun).order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
    if after:
        cursor = await db.get(TaskRun, after)
        if not cursor:
            raise HTTPException(status_code=400, detail={"code": "invalid_cursor", "message": "Run cursor was not found."})
        statement = statement.where(TaskRun.created_at <= cursor.created_at, TaskRun.id != cursor.id)
    rows = (await db.execute(statement.limit(limit + 1))).scalars().all()
    items = rows[:limit]
    response.headers["X-Result-Count"] = str(len(items))
    response.headers["X-Has-More"] = str(len(rows) > limit).lower()
    response.headers["X-Next-Cursor"] = items[-1].id if items else (after or "")
    return [item.to_dict() for item in items]


@runs_router.get("/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    return (await _require_run(db, run_id)).to_dict()


@runs_router.get("/{run_id}/attempts")
async def list_run_attempts(run_id: str, db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    rows = (await db.execute(select(RunAttemptRecord).where(RunAttemptRecord.run_id == run_id).order_by(RunAttemptRecord.attempt_number))).scalars().all()
    return [item.to_dict() for item in rows]


@runs_router.get("/{run_id}/events")
async def list_run_events(run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    return await event_journal.replay(run_id, after_sequence=after, limit=limit)


@runs_router.get("/{run_id}/output")
async def list_run_output(run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    return [record.to_dict() for record in await run_output_service.list(db, run_id, after, limit)]


@runs_router.get("/{run_id}/artifacts")
async def list_run_artifacts(run_id: str, db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    return [record.to_dict() for record in await run_artifact_service.list(db, run_id)]


@runs_router.get("/{run_id}/usage")
async def get_run_usage(run_id: str, db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    return await usage_service.aggregate(db, run_id)


@runs_router.get("/{run_id}/efficiency")
async def get_run_efficiency(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _require_run(db, run_id)
    usage = await usage_service.aggregate(db, run_id)
    return efficiency_service.calculate(run, usage)


@runs_router.get("/{run_id}/latency")
async def get_run_latency(run_id: str, db: AsyncSession = Depends(get_db)):
    await _require_run(db, run_id)
    return await latency_service.aggregate(db, run_id)


@runs_router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _require_run(db, run_id)
    if run.status in {"completed", "failed", "timed_out", "cancelled", "interrupted"}:
        raise HTTPException(status_code=409, detail={"code": "run_terminal", "message": "Run is already terminal."})
    await run_lifecycle_service.request_cancel(db, run_id)
    local_cancelled, provider_cancelled = await asyncio.gather(process_manager.cancel(run_id), provider_runtime_registry.cancel(run_id))
    return {"run_id": run_id, "status": "cancellation_requested", "execution_found": local_cancelled or provider_cancelled}


@task_router.post("/preflight")
async def preflight_task(req: TaskRunRequest):
    """Verify a real provider or authenticated CLI route before execution."""
    return await build_execution_preflight(
        prompt=req.prompt,
        routing_mode=req.routing_mode,
        model_id=req.model_id,
        agent_id=req.agent_id,
        workspace_id=req.workspace_id,
        interactive=req.interactive,
    )


@task_router.post("/run")
async def run_task(req: TaskRunRequest, db: AsyncSession = Depends(get_db)):
    """Execute a task with REAL LLM / CLI execution and live financial tracking."""
    task_id = req.task_id or f"task-{uuid.uuid4().hex[:8]}"
    if await db.get(TaskRun, task_id):
        raise HTTPException(status_code=409, detail={"code": "duplicate_task_id", "message": "A persisted run already uses this task id."})
    start_time = time.time()
    try:
        await run_lifecycle_service.create(db, run_id=task_id, prompt=req.prompt, routing_mode=req.routing_mode, workspace_id=req.workspace_id)
        await run_lifecycle_service.start(db, task_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    preflight = await build_execution_preflight(
        prompt=req.prompt,
        routing_mode=req.routing_mode,
        model_id=req.model_id,
        agent_id=req.agent_id,
        workspace_id=req.workspace_id,
        interactive=req.interactive,
    )
    if not preflight["can_execute"]:
        await task_event_bus.publish(task_id, "blocked", message="Execution stopped: no connected provider or authenticated CLI route is available.", blockers=preflight["blockers"])
        await run_lifecycle_service.finalize(db, task_id, "failed", "execution_not_ready")
        raise HTTPException(
            status_code=409,
            detail={"code": "execution_not_ready", "message": "Execution preflight failed.", "preflight": preflight},
        )

    await task_event_bus.publish(task_id, "system", message="Preflight passed. Starting real execution.")
    recommendation = preflight["recommendation"]
    explanation = recommendation["explanation"]
    fallback_chain = recommendation["fallback_chain"]
    execution_method = preflight["execution_method"]
    model = await db.get(ModelRecord, preflight["selected_model"]["id"]) if preflight["selected_model"] else None
    agent = await db.get(AgentRecord, preflight["selected_agent"]["id"]) if preflight["selected_agent"] else None
    attempt = await run_lifecycle_service.start_attempt(
        db,
        task_id,
        execution_method,
        agent_id=agent.id if agent else None,
        model_id=model.id if model else None,
        provider_instance_id=model.provider if model and execution_method == "provider_api" else None,
    )

    route_name = agent.name if agent else model.name
    explanation = (
        f"Authenticated local CLI route: {agent.name}."
        if agent
        else f"Connected provider route: {model.name} ({model.provider})."
    )
    await task_event_bus.publish(
        task_id,
        "route",
        message=f"Verified {route_name} for live execution.",
        model_id=model.id if model else None,
        agent_id=agent.id if agent else None,
        execution_method=execution_method,
    )

    base_res = await db.execute(select(SystemSetting.value).where(SystemSetting.key == "reference_baseline_model"))
    baseline_id = base_res.scalar_one_or_none() or "gpt-4o"
    baseline_model = await db.get(ModelRecord, baseline_id)
    await task_event_bus.publish(task_id, "execution", message=f"Execution started with {route_name}.", agent_id=agent.id if agent else None)

    # 2. REAL provider or authenticated CLI execution
    chunks = []
    stderr_chunks = []
    output_chunks_to_persist: List[Dict[str, str]] = []
    total_tokens_generated = 0
    execution_error = ""
    execution_outcome = "completed"
    first_output_at: Optional[float] = None

    if execution_method == "cli" and agent:
        workspace_record = await db.get(WorkspaceRecord, req.workspace_id or preflight["selected_workspace"]["id"])
        if not workspace_record:
            raise HTTPException(status_code=409, detail="Approved workspace is required for CLI execution.")
        workspace = workspace_record.path
        execution_cwd = workspace if agent.working_directory == "workspace" else None
        workspace_record.last_used_at = datetime.utcnow()

        async def on_cli_chunk(text: str, stream_type: str):
            nonlocal first_output_at
            if text and first_output_at is None:
                first_output_at = time.time()
            output_chunks_to_persist.append({"stream": stream_type, "content": text})
            if stream_type in {"stdout", "terminal"}:
                chunks.append(text)
                await task_event_bus.publish(task_id, "terminal" if stream_type == "terminal" else "output", text=text)
            else:
                stderr_chunks.append(text)
                await task_event_bus.publish(task_id, "log", text=text)

        try:
            cli_args = build_cli_args(agent, req.prompt, workspace)
            if req.interactive:
                cli_result = await process_manager.execute_pty(
                    cli_args,
                    task_id=task_id,
                    cwd=execution_cwd,
                    on_chunk=on_cli_chunk,
                    columns=req.terminal_columns,
                    rows=req.terminal_rows,
                    initial_stdin=f"{req.prompt}\r\n" if agent.input_method == "stdin" else None,
                )
            else:
                cli_result = await process_manager.execute_argv(
                    cli_args,
                    task_id=task_id,
                    cwd=execution_cwd,
                    on_chunk=on_cli_chunk,
                )
            execution_outcome = cli_result["outcome"]
            if not cli_result["success"]:
                execution_error = cli_result["stderr"].strip() or f"{agent.name} exited with code {cli_result['exit_code']}."
        except DuplicateTaskIdError as exc:
            raise HTTPException(status_code=409, detail={"code": "duplicate_active_task_id", "message": str(exc)}) from exc
        except ValueError as exc:
            execution_error = str(exc)
    elif model:
        adapter = provider_runtime_registry.resolve(model.provider)
        async for event in adapter.stream(model.id, req.prompt, task_id):
            if event.event_type == "chunk":
                output_chunks_to_persist.append({"stream": "output", "content": event.text})
                if event.text and first_output_at is None:
                    first_output_at = time.time()
                chunks.append(event.text)
                await task_event_bus.publish(task_id, "output", text=event.text)
            elif event.event_type == "done":
                total_tokens_generated = event.usage.output_tokens if event.usage and event.usage.output_tokens is not None else 0
            elif event.event_type in {"error", "cancelled"}:
                execution_error = event.text or ("Execution was cancelled." if event.event_type == "cancelled" else "Live execution failed.")
                execution_outcome = "cancelled" if event.event_type == "cancelled" else "non_zero_exit"

    if execution_error:
        await task_event_bus.publish(task_id, "error", message=execution_error)

    output_text = "".join(chunks)
    duration_ms = int((time.time() - start_time) * 1000)

    # 3. Calculate exact tokens & financials
    input_tok = int(len(req.prompt.split()) * 1.35)
    output_tok = max(total_tokens_generated, int(len(output_text.split()) * 1.35))
    cached_tok = int(input_tok * 0.3) if model and not model.is_local else 0

    price_time = datetime.utcnow()
    usage_values = {"input_tokens": input_tok, "output_tokens": output_tok, "cached_tokens": cached_tok, "reasoning_tokens": 0}
    usage_sources = {"input_tokens": "estimated", "output_tokens": "provider_reported" if total_tokens_generated > 0 and execution_method == "provider_api" else "estimated", "cached_tokens": "estimated", "reasoning_tokens": "unknown"}
    required_price_dimensions = {"input", "output"} | ({"cache"} if cached_tok > 0 else set())
    actual_price = await pricing_service.resolve(db, model.id, price_time, required_dimensions=required_price_dimensions) if model and not execution_error and execution_method == "provider_api" and not model.is_local else None
    baseline_price = await pricing_service.resolve(db, baseline_model.id, price_time, required_dimensions=required_price_dimensions) if baseline_model and not execution_error else None
    unknown_cost = CostResult(None, None, "unknown", None, None, None, {"reason": "non_billed_execution_or_price_unavailable"})
    actual_result = cost_calculator.formula(usage_values, actual_price, usage_sources) if actual_price else unknown_cost
    reference_result = cost_calculator.formula(usage_values, baseline_price, usage_sources) if baseline_price else CostResult(None, None, "unknown", None, None, None, {"reason": "baseline_price_unavailable"})
    savings_result = savings_calculator.compare(actual_result, reference_result, "estimated_avoided_cost")
    actual_cost = float(actual_result.amount) if actual_result.amount is not None else 0.0
    ref_cost = float(reference_result.amount) if reference_result.amount is not None else 0.0
    saved_amount = float(savings_result.amount) if savings_result.amount is not None else 0.0
    saving_pct = (saved_amount / ref_cost * 100.0) if savings_result.amount is not None and ref_cost > 0 else 0.0
    actual_cost_known = actual_result.amount is not None

    task_analysis = model_router.classify_task(req.prompt)

    run_status = "cancelled" if execution_outcome == "cancelled" else ("timed_out" if execution_outcome == "timed_out" else ("failed" if execution_error else "completed"))
    run_record = await db.get(TaskRun, task_id)
    run_record.task_type = task_analysis["category"]
    run_record.selected_model_id = model.id if model else None
    run_record.selected_agent_id = agent.id if agent else None
    run_record.workspace_id = preflight["selected_workspace"]["id"] if preflight.get("selected_workspace") else None
    run_record.input_tokens = input_tok
    run_record.output_tokens = output_tok
    run_record.cached_tokens = cached_tok
    run_record.actual_cost = actual_cost
    run_record.reference_cost = ref_cost
    run_record.saved_amount = saved_amount
    run_record.saving_percentage = saving_pct
    run_record.duration_ms = duration_ms
    run_record.quality_eval_score = None
    run_record.token_provenance = "estimated"
    run_record.cost_provenance = actual_result.provenance
    run_record.quality_provenance = "unknown"
    run_record.latency_provenance = "measured"
    run_record.measurement_metadata = json.dumps({
        "tokens": {"method": "word_count_multiplier", "multiplier": 1.35},
        "duration": {"method": "wall_clock"},
    })
    run_record.financials_json = json.dumps({"actual_cost": actual_result.to_dict(), "reference_cost": reference_result.to_dict(), "value": savings_result.to_dict()})
    run_record.route_explanation = explanation
    run_record.fallback_chain = json.dumps(fallback_chain)
    run_record.log_output = (
        f"[{datetime.utcnow().strftime('%H:%M:%S')}] Verified route -> {route_name} ({execution_method})\n"
        f"[{datetime.utcnow().strftime('%H:%M:%S')}] {'Failed: ' + execution_error if execution_error else f'Completed in {duration_ms}ms.'}"
        f"\nCost evidence: {'resolved' if actual_cost_known else 'unknown'}"
        + (f"\n{''.join(stderr_chunks).strip()}" if stderr_chunks else "")
    )
    run_record.result_output = output_text if not execution_error else ""
    await usage_service.record(db, {
        "run_id": task_id,
        "model_id": model.id if model else None,
        "requests": 1,
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cached_tokens": cached_tok,
        "source": "estimated",
        "method": "word_count_multiplier",
        "metadata": {"multiplier": 1.35},
        "observed_at": datetime.utcnow(),
    })
    if total_tokens_generated > 0 and execution_method == "provider_api":
        await usage_service.record(db, {
            "run_id": task_id,
            "model_id": model.id if model else None,
            "output_tokens": total_tokens_generated,
            "source": "provider_reported",
            "observed_at": datetime.utcnow(),
        })
    ttft_ms = int((first_output_at - start_time) * 1000) if first_output_at is not None else None
    generation_seconds = max((time.time() - first_output_at), 0.001) if first_output_at is not None else None
    throughput = (total_tokens_generated / generation_seconds) if total_tokens_generated > 0 and generation_seconds else None
    attempt_receipt = cli_result if execution_method == "cli" and 'cli_result' in locals() else {
        "execution_type": "provider", "outcome": execution_outcome, "duration_ms": duration_ms,
        "error": execution_error or None, "output_chars": len(output_text),
    }
    await run_lifecycle_service.finalize_attempt(
        db,
        attempt.id,
        status=run_status,
        outcome=execution_outcome,
        receipt=attempt_receipt,
        error_code="execution_failed" if execution_error and run_status != "cancelled" else ("execution_cancelled" if run_status == "cancelled" else None),
    )
    await run_output_service.append_many(db, task_id, output_chunks_to_persist, attempt.id)
    await latency_service.record(db, {
        "run_id": task_id,
        "ttft_ms": ttft_ms,
        "duration_ms": duration_ms,
        "tokens_per_second": throughput,
        "source": "measured",
        "method": "wall_clock",
        "observed_at": datetime.utcnow(),
    })
    await db.commit()
    run_record = await run_lifecycle_service.finalize(db, task_id, run_status, "execution_failed" if execution_error else None)
    return run_record.to_dict()


@task_router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    local_cancelled, provider_cancelled = await asyncio.gather(
        process_manager.cancel(task_id),
        provider_runtime_registry.cancel(task_id),
    )
    if not local_cancelled and not provider_cancelled:
        raise HTTPException(status_code=404, detail={"code": "active_execution_not_found", "message": "No active execution exists for this task."})
    await task_event_bus.publish(task_id, "cancellation_requested", message="Cancellation requested. Waiting for the execution receipt.")
    return {"task_id": task_id, "status": "cancellation_requested", "state": process_manager.get_state(task_id) or "cancellation_requested", "execution_type": "local" if local_cancelled else "provider"}


class RunArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    artifact_type: str = Field(default="other", max_length=32)
    attempt_id: Optional[str] = Field(default=None, max_length=64)
    metadata: Dict[str, Any] = Field(default_factory=dict, max_length=50)


@task_router.get("/{task_id}/artifacts")
async def list_task_artifacts(task_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await run_artifact_service.list(db, task_id)]


@task_router.post("/{task_id}/artifacts")
async def register_task_artifact(task_id: str, request: RunArtifactRequest, db: AsyncSession = Depends(get_db)):
    try:
        record = await run_artifact_service.register(db, task_id, request.path, request.artifact_type, request.attempt_id, request.metadata)
        return record.to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@task_router.get("/{task_id}/output")
async def get_task_output(task_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await run_output_service.list(db, task_id, after, limit)]


@task_router.get("/{task_id}/usage")
async def get_task_usage(task_id: str, db: AsyncSession = Depends(get_db)):
    return await usage_service.aggregate(db, task_id)


@task_router.get("/{task_id}/latency")
async def get_task_latency(task_id: str, db: AsyncSession = Depends(get_db)):
    return await latency_service.aggregate(db, task_id)


@task_router.get("/{task_id}/execution")
async def get_task_execution(task_id: str):
    state = process_manager.get_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail={"code": "execution_not_found", "message": "No active or recent local execution was found."})
    return process_manager.get_status(task_id)


@task_router.get("/history")
async def get_task_history(response: Response, limit: int = Query(default=50, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(limit + 1))).scalars().all()
    items = rows[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Result-Count"] = str(len(items))
    response.headers["X-Has-More"] = str(len(rows) > limit).lower()
    return [item.to_dict() for item in items]


# --- Conversational Chat Studio Router ---
chat_router = APIRouter(prefix="/api/chat", tags=["Chat Studio"])


@chat_router.get("/sessions")
async def list_chat_sessions(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc()))
    sessions = res.scalars().all()
    if not sessions:
        # Create initial default session
        init_sess = ChatSession(id="session-default", title="Primary TEMM Workspace")
        db.add(init_sess)
        await db.commit()
        sessions = [init_sess]
    return [s.to_dict() for s in sessions]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default="New Conversation", max_length=256)
    model_id: Optional[str] = Field(default="auto", max_length=128)
    routing_mode: Optional[str] = Field(default="balanced", max_length=32)


@chat_router.post("/sessions")
async def create_chat_session(req: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    sess_id = f"session-{uuid.uuid4().hex[:8]}"
    sess = ChatSession(
        id=sess_id,
        title=req.title or "New Conversation",
        model_id=req.model_id or "auto",
        routing_mode=req.routing_mode or "balanced",
    )
    db.add(sess)
    await db.commit()
    return sess.to_dict()


@chat_router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc()))
    return [m.to_dict() for m in res.scalars().all()]


class SendChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=262144)
    model_id: Optional[str] = Field(default="auto", max_length=128)
    routing_mode: Optional[str] = Field(default="balanced", max_length=32)


@chat_router.post("/send")
async def send_chat_message(req: SendChatMessageRequest, db: AsyncSession = Depends(get_db)):
    """Send user message and receive real streaming/completed AI response."""
    start_time = time.time()
    
    # 1. Save User Message
    user_msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    user_msg = ChatMessage(
        id=user_msg_id,
        session_id=req.session_id,
        role="user",
        content=req.message,
        tokens=int(len(req.message.split()) * 1.35),
    )
    db.add(user_msg)
    await db.flush()

    # 2. Pick Model
    if not req.model_id or req.model_id == "auto":
        rec = await model_router.recommend_model(prompt=req.message, mode=req.routing_mode or "balanced")
        chosen_model_id = rec["selected_model"]["id"]
    else:
        chosen_model_id = req.model_id

    model = await db.get(ModelRecord, chosen_model_id)
    if not model:
        model = (await db.execute(select(ModelRecord))).scalars().first()

    base_res = await db.execute(select(SystemSetting.value).where(SystemSetting.key == "reference_baseline_model"))
    baseline_id = base_res.scalar_one_or_none() or "gpt-4o"
    baseline_model = await db.get(ModelRecord, baseline_id) or model

    # 3. Stream real response through the provider contract
    chunks = []
    total_tokens_gen = 0
    execution_error = ""
    provider_adapter = provider_runtime_registry.resolve(model.provider)
    async for event in provider_adapter.stream(model.id, req.message, f"chat-{user_msg_id}"):
        if event.event_type == "chunk":
            chunks.append(event.text)
        elif event.event_type == "done":
            total_tokens_gen = event.usage.output_tokens if event.usage and event.usage.output_tokens is not None else 0
        elif event.event_type in {"error", "cancelled"}:
            execution_error = event.text or "Live execution failed."

    if execution_error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "execution_not_ready",
                "message": execution_error,
            },
        )

    response_text = "".join(chunks)
    duration_ms = int((time.time() - start_time) * 1000)

    # 4. Financial calculation
    in_tok = user_msg.tokens
    out_tok = max(total_tokens_gen, int(len(response_text.split()) * 1.35))
    price_time = datetime.utcnow()
    price = await pricing_service.resolve(db, model.id, price_time)
    baseline_price = await pricing_service.resolve(db, baseline_model.id, price_time)
    if model.is_local:
        cost = 0.0
        cost_known = True
    elif price:
        cost = ((in_tok / 1_000_000.0) * (price.input_per_m or 0)) + ((out_tok / 1_000_000.0) * (price.output_per_m or 0))
        cost_known = True
    else:
        cost = 0.0
        cost_known = False
    ref_cost = ((in_tok / 1_000_000.0) * (baseline_price.input_per_m or 0)) + ((out_tok / 1_000_000.0) * (baseline_price.output_per_m or 0)) if baseline_price else 0.0
    saved = max(0.0, ref_cost - cost) if cost_known and baseline_price else 0.0

    # 5. Save Assistant Message
    asst_msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    asst_msg = ChatMessage(
        id=asst_msg_id,
        session_id=req.session_id,
        role="assistant",
        content=response_text,
        model_used=model.name,
        provider_used=model.provider,
        tokens=in_tok + out_tok,
        cost=cost,
        saved=saved,
        latency_ms=duration_ms,
    )
    db.add(asst_msg)

    # Update session title if first turn
    sess = await db.get(ChatSession, req.session_id)
    if sess:
        if sess.title == "New Conversation" or sess.title == "Primary TEMM Workspace":
            sess.title = req.message[:38] + ("..." if len(req.message) > 38 else "")
        sess.total_tokens += (in_tok + out_tok)
        sess.total_saved += saved
        sess.updated_at = datetime.utcnow()

    await db.commit()

    return {
        "user_message": user_msg.to_dict(),
        "assistant_message": asst_msg.to_dict(),
        "model_used": model.name,
        "saved_vs_baseline": f"${saved:.5f}",
        "duration_ms": duration_ms,
    }


# --- Audit Router ---
audit_router = APIRouter(prefix="/api/audit", tags=["Audit"])


@audit_router.get("")
async def query_audit(
    response: Response,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    action: Optional[str] = Query(default=None, max_length=128),
    resource_type: Optional[str] = Query(default=None, max_length=64),
    resource_id: Optional[str] = Query(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    records = await audit_service.query(db, after_sequence=after, limit=limit, action=action, resource_type=resource_type, resource_id=resource_id)
    response.headers["X-Result-Count"] = str(len(records))
    response.headers["X-Next-Cursor"] = str(records[-1].sequence if records else after)
    return [record.to_dict() for record in records]


# --- Approval Router ---
approvals_router = APIRouter(prefix="/api/approvals", tags=["Approvals"])


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: str = Field(min_length=1, max_length=64)
    scope_type: str = Field(min_length=1, max_length=64)
    scope_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=512)
    details: Dict[str, Any] = Field(default_factory=dict, max_length=50)
    ttl_seconds: int = Field(default=900, ge=30, le=86400)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    reason: str = Field(default="", max_length=1000)


@approvals_router.get("")
async def list_approvals(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await approval_service.list(db, status)]


@approvals_router.post("")
async def request_approval(request: ApprovalRequest, db: AsyncSession = Depends(get_db)):
    try:
        record = await approval_service.request(db, **request.model_dump())
        return record.to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@approvals_router.post("/{approval_id}/decision")
async def decide_approval(approval_id: str, decision: ApprovalDecision, db: AsyncSession = Depends(get_db)):
    try:
        record = await approval_service.decide(db, approval_id, decision.approve, decision.reason)
        return record.to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


# --- Terminal Runner Router ---
terminal_router = APIRouter(prefix="/api/terminal", tags=["Terminal"])


@terminal_router.get("/capabilities")
async def get_terminal_capabilities():
    return process_manager.pty_capability()


class TerminalExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=262144)
    shell: str = Field(default="powershell", max_length=32)
    workspace_id: Optional[str] = Field(default=None, max_length=64)
    approval_id: Optional[str] = Field(default=None, max_length=64)


@terminal_router.post("/run")
async def run_terminal_command(req: TerminalExecRequest, db: AsyncSession = Depends(get_db)):
    """Execute a user-confirmed command inside an approved workspace."""
    start_time = time.time()
    probe_parts = req.command.strip().lower().split()
    is_read_only_probe = bool(probe_parts) and probe_parts[-1] in {"--version", "-v", "version"} and len(probe_parts) <= 3
    workspace = await db.get(WorkspaceRecord, req.workspace_id) if req.workspace_id else None
    if not workspace and not is_read_only_probe:
        raise HTTPException(status_code=400, detail="Choose an approved workspace before running a command.")
    if workspace and not req.approval_id:
        raise HTTPException(status_code=403, detail={"code": "approval_required", "message": "A scoped command approval is required."})
    if workspace and req.approval_id:
        try:
            await approval_service.consume(db, req.approval_id, "command", "workspace", workspace.id)
        except DomainError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    if workspace and req.shell not in workspace.to_dict()["allowed_shells"]:
        raise HTTPException(status_code=403, detail=f"{req.shell} is not allowed in this workspace.")

    record = None
    if workspace:
        record = CommandRunRecord(
            id=f"command-{uuid.uuid4().hex[:8]}",
            workspace_id=workspace.id,
            command=req.command,
            shell=req.shell,
            status="running",
        )
        db.add(record)
        await db.flush()
    try:
        if req.shell == "powershell":
            full_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", req.command]
        else:
            full_cmd = ["cmd", "/d", "/s", "/c", req.command]
        execution_id = record.id if record else f"probe-{uuid.uuid4().hex[:8]}"
        execution = await process_manager.execute_argv(
            full_cmd,
            task_id=execution_id,
            cwd=workspace.path if workspace else None,
            timeout_seconds=30.0,
        )
        result = {
            "id": record.id if record else None,
            "execution_id": execution_id,
            "workspace_id": workspace.id if workspace else None,
            "command": req.command,
            "exit_code": execution["exit_code"],
            "stdout": execution["stdout"],
            "stderr": execution["stderr"],
            "duration_ms": execution["duration_ms"],
            "success": execution["success"],
            "state": execution["state"],
            "outcome": execution["outcome"],
            "error_code": execution["error_code"],
        }
        if record:
            record.status = execution["state"]
            record.exit_code = execution["exit_code"]
            record.stdout = execution["stdout"]
            record.stderr = execution["stderr"]
            record.duration_ms = execution["duration_ms"]
            workspace.last_used_at = datetime.utcnow()
            await db.commit()
        return result
    except DuplicateTaskIdError as exc:
        raise HTTPException(status_code=409, detail={"code": "duplicate_active_task_id", "message": str(exc)}) from exc
    except Exception as e:
        result = {
            "id": record.id if record else None,
            "workspace_id": workspace.id if workspace else None,
            "command": req.command,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "duration_ms": int((time.time() - start_time) * 1000),
            "success": False,
        }
        if record:
            record.status = "failed"
            record.exit_code = 1
            record.stderr = result["stderr"]
            record.duration_ms = result["duration_ms"]
            await db.commit()
        return result


@terminal_router.get("/history")
async def get_command_history(response: Response, workspace_id: Optional[str] = None, limit: int = Query(default=50, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    stmt = select(CommandRunRecord).order_by(CommandRunRecord.created_at.desc()).limit(limit + 1)
    if workspace_id:
        stmt = stmt.where(CommandRunRecord.workspace_id == workspace_id)
    rows = (await db.execute(stmt)).scalars().all()
    items = rows[:limit]
    response.headers["X-Page-Limit"] = str(limit)
    response.headers["X-Result-Count"] = str(len(items))
    response.headers["X-Has-More"] = str(len(rows) > limit).lower()
    return [record.to_dict() for record in items]


# --- Benchmarks Router ---
benchmarks_router = APIRouter(prefix="/api/benchmarks", tags=["Benchmarks"])


class BenchmarkPackImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=1024)


@benchmarks_router.post("/packs/import")
async def import_benchmark_pack(request: BenchmarkPackImportRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await benchmark_pack_service.import_file(db, request.workspace_id, request.path)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@benchmarks_router.get("/versions/{version_id}/export")
async def export_benchmark_pack(version_id: str, format: str = Query(default="json", pattern="^(json|yaml)$"), db: AsyncSession = Depends(get_db)):
    try:
        content = await benchmark_pack_service.export(db, version_id, format)
        media_type = "application/json" if format == "json" else "application/yaml"
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="benchmark-pack.{format}"'})
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class BenchmarkCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=100000)
    expected_behavior: str = Field(min_length=1, max_length=100000)
    evaluator_type: str = Field(max_length=32)
    evaluator_config: Dict[str, Any] = Field(default_factory=dict, max_length=100)
    category: str = Field(default="general", max_length=64)
    difficulty: str = Field(default="medium", max_length=32)
    weight: float = Field(default=1.0, gt=0)
    provenance: str = Field(default="user_authored", max_length=32)


class BenchmarkSuiteVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_key: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    provenance: str = Field(default="user_authored", max_length=32)
    source_uri: str = Field(default="", max_length=1024)
    cases: List[BenchmarkCaseRequest] = Field(min_length=1, max_length=10000)


@benchmarks_router.post("/suites/versions")
async def create_benchmark_suite_version(request: BenchmarkSuiteVersionRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await benchmark_suite_service.create_version(db, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@benchmarks_router.get("/suites/{suite_key}/versions")
async def list_benchmark_suite_versions(suite_key: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await benchmark_suite_service.list_versions(db, suite_key)]


@benchmarks_router.get("/versions/{version_id}/cases")
async def list_benchmark_cases(version_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await benchmark_suite_service.cases(db, version_id)]


@benchmarks_router.get("")
async def list_benchmarks(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(BenchmarkRecord))
    return [b.to_dict() for b in res.scalars().all()]


@benchmarks_router.get("/leaderboard")
async def get_leaderboard(suite_version_id: str, category: Optional[str] = None, max_age_days: int = Query(default=365, ge=1, le=3650), db: AsyncSession = Depends(get_db)):
    try:
        return await personal_leaderboard_service.rank(db, suite_version_id, category, max_age_days)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class CommunityConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@benchmarks_router.put("/community/consent")
async def set_community_leaderboard_consent(request: CommunityConsentRequest, db: AsyncSession = Depends(get_db)):
    return await community_leaderboard_service.consent(db, request.enabled)


@benchmarks_router.get("/community/preview")
async def preview_community_leaderboard(suite_version_id: str, max_age_days: int = Query(default=365, ge=1, le=3650), db: AsyncSession = Depends(get_db)):
    try:
        return await community_leaderboard_service.preview(db, suite_version_id, max_age_days)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@benchmarks_router.post("/community/export")
async def export_community_leaderboard(suite_version_id: str, max_age_days: int = Query(default=365, ge=1, le=3650), db: AsyncSession = Depends(get_db)):
    try:
        return await community_leaderboard_service.export(db, suite_version_id, max_age_days)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class RealBenchmarkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_version_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    workspace_id: str = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=120, ge=1, le=1800)
    execution_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,47}$")


@benchmarks_router.post("/run-real")
async def run_real_benchmark(request: RealBenchmarkRunRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await benchmark_runner_service.run(db, request.suite_version_id, request.agent_id, request.workspace_id, request.timeout_seconds, request.execution_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


class RunBenchmarkRequest(BaseModel):
    benchmark_id: str
    model_ids: List[str]


@benchmarks_router.post("/run")
async def run_benchmark(req: RunBenchmarkRequest):
    raise HTTPException(
        status_code=501,
        detail={
            "code": "real_benchmark_runner_required",
            "message": "Simulated benchmark scoring is disabled. Connect real executors and a judge before running this suite.",
        },
    )


# --- Arena Router ---
arena_router = APIRouter(prefix="/api/arena", tags=["Arena"])


@arena_router.get("/pair")
async def get_blind_pair(prompt: Optional[str] = None):
    raise HTTPException(
        status_code=501,
        detail={"code": "real_arena_required", "message": "The synthetic arena is disabled until two real executors are connected."},
    )


class ArenaCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_a_id: str = Field(min_length=1, max_length=64)
    run_b_id: str = Field(min_length=1, max_length=64)


class ArenaVoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    winner: str = Field(pattern="^(a|b|tie)$")


@arena_router.post("/sessions")
async def create_arena_session(request: ArenaCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await arena_service.create(db, request.run_a_id, request.run_b_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@arena_router.get("/sessions/{arena_id}")
async def get_arena_session(arena_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await arena_service.get(db, arena_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@arena_router.post("/sessions/{arena_id}/vote")
async def submit_arena_vote(arena_id: str, request: ArenaVoteRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await arena_service.vote(db, arena_id, request.winner)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@arena_router.post("/vote")
async def submit_legacy_arena_vote():
    raise HTTPException(status_code=410, detail={"code": "legacy_arena_vote_removed", "message": "Create a persisted blind arena session before voting."})


# --- Skills Router ---
skills_router = APIRouter(prefix="/api/skills", tags=["Skills"])


@skills_router.get("")
async def list_skills(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(DelegateSkillRecord))
    return [s.to_dict() for s in res.scalars().all()]


class ImportSkillsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_path: str = Field(min_length=1, max_length=1024)


@skills_router.post("/import-folder")
async def import_skills_folder(req: ImportSkillsRequest):
    return await skill_adapter.import_skills_folder(req.folder_path)


class RunSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(min_length=1, max_length=64)
    task_input: str = Field(min_length=1, max_length=262144)
    workspace_id: Optional[str] = Field(default=None, max_length=64)


@skills_router.post("/run")
async def run_skill(req: RunSkillRequest):
    workspace_path = None
    if req.workspace_id:
        async with AsyncSessionLocal() as session:
            workspace = await session.get(WorkspaceRecord, req.workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found.")
            workspace_path = workspace.path
            permission_profile = workspace.permission_profile
    try:
        return await skill_adapter.run_skill(req.skill_id, req.task_input, workspace=workspace_path, permission_profile=permission_profile if workspace_path else "safe")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- Workflows Router ---
workflows_router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


@workflows_router.get("")
async def list_workflows(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(WorkflowRecord))
    return [w.to_dict() for w in res.scalars().all()]


class RunWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=1, max_length=64)
    input_text: str = Field(min_length=1, max_length=262144)


@workflows_router.post("/run")
async def run_workflow(req: RunWorkflowRequest, db: AsyncSession = Depends(get_db)):
    """Execute a workflow DAG with real CLI execution per task node."""
    workflow = await db.get(WorkflowRecord, req.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail={"code": "workflow_not_found", "message": "Workflow was not found."})
    nodes_data = json.loads(workflow.nodes) if isinstance(workflow.nodes, str) else workflow.nodes
    edges_data = json.loads(workflow.edges) if isinstance(workflow.edges, str) else workflow.edges
    if not nodes_data:
        raise HTTPException(status_code=422, detail={"code": "workflow_empty", "message": "Workflow has no nodes."})
    from ..workflow_contract import WorkflowDefinition, WorkflowEdge, WorkflowPort
    from ..workflow_nodes import build_node
    from ..services.workflow_runner import workflow_runner_service
    try:
        wf_nodes = [build_node(n.get("type", "task"), n.get("id", f"node-{i}")) for i, n in enumerate(nodes_data)]
        wf_edges = [WorkflowEdge(e["source"], e.get("sourcePort", "output"), e["target"], e.get("targetPort", "input")) for e in edges_data]
        definition = WorkflowDefinition(workflow.id, "1", wf_nodes, wf_edges, [WorkflowPort("goal", "text")], [WorkflowPort("result", "any")])
        definition.validate()
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "workflow_invalid", "message": str(exc)}) from exc
    # Create a real executor using process_manager for task nodes
    run_id = f"workflow-run-{uuid.uuid4().hex[:8]}"
    await run_lifecycle_service.create(db, run_id=run_id, prompt=req.input_text, routing_mode="balanced", workflow_id=workflow.id)
    await run_lifecycle_service.start(db, run_id)
    control: Dict[str, bool] = {}
    async def real_executor(node_id: str, node_type: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if node_type in {"output", "classify", "router"}:
            return {"status": "completed", "outputs": inputs, "evidence": {"type": "passthrough", "node_type": node_type}}
        # For task/agent/judge/critic/gate nodes, execute through process_manager
        preflight_result = await build_execution_preflight(prompt=inputs.get("goal", req.input_text), routing_mode="balanced")
        if not preflight_result["can_execute"]:
            return {"status": "failed", "outputs": {}, "evidence": {"type": "execution_blocked", "blockers": preflight_result["blockers"]}}
        agent = await db.get(AgentRecord, preflight_result["selected_agent"]["id"]) if preflight_result.get("selected_agent") else None
        if not agent:
            return {"status": "failed", "outputs": {}, "evidence": {"type": "no_agent_available"}}
        workspace = await db.get(WorkspaceRecord, preflight_result["selected_workspace"]["id"]) if preflight_result.get("selected_workspace") else None
        if not workspace:
            return {"status": "failed", "outputs": {}, "evidence": {"type": "no_workspace"}}
        attempt = await run_lifecycle_service.start_attempt(db, run_id, "cli", agent_id=agent.id)
        argv = build_cli_args(agent, inputs.get("goal", req.input_text), workspace.path)
        receipt = await process_manager.execute_argv(argv, f"wf-{run_id}-{node_id}", cwd=workspace.path, timeout_seconds=120)
        status = "completed" if receipt["outcome"] == "completed" else "failed"
        await run_lifecycle_service.finalize_attempt(db, attempt.id, status=status, outcome=receipt["outcome"], receipt={k: v for k, v in receipt.items() if k not in {"stdout", "stderr"}}, error_code=receipt.get("error_code"))
        return {"status": status, "outputs": {"result": receipt.get("stdout", ""), "output": receipt.get("stdout", "")}, "evidence": {"type": "real_execution", "run_id": run_id, "attempt_id": attempt.id, "agent_id": agent.id, "duration_ms": receipt.get("duration_ms"), "exit_code": receipt.get("exit_code")}}
    try:
        result = await workflow_runner_service.run(definition, {"goal": req.input_text}, real_executor, control)
    except DomainError as exc:
        await run_lifecycle_service.finalize(db, run_id, "failed", exc.code)
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    final_status = "completed" if result["status"] == "completed" else "cancelled" if result["status"] == "cancelled" else "failed"
    await run_lifecycle_service.finalize(db, run_id, final_status)
    return {"workflow_id": workflow.id, "run_id": run_id, "status": result["status"], "events": result["events"], "simulated": result.get("simulated", False), "node_count": len(wf_nodes)}


# --- Provider Registry Router ---
providers_router = APIRouter(prefix="/api/providers", tags=["Providers"])


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(default=None, min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    adapter_id: str = Field(min_length=1, max_length=128)
    capabilities: List[str] = Field(default_factory=list, max_length=16)
    configuration: Dict[str, Any] = Field(default_factory=dict, max_length=50)


class ProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    capabilities: Optional[List[str]] = Field(default=None, max_length=16)
    configuration: Optional[Dict[str, Any]] = Field(default=None, max_length=50)
    user_enabled: Optional[bool] = None


class ProviderModelObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    modalities: List[str] = Field(default=["text"], min_length=1, max_length=8)


class ProviderModelIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: List[ProviderModelObservationRequest] = Field(max_length=1000)
    ttl_seconds: int = Field(default=300, ge=10, le=86400)


class ProviderQuotaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field(min_length=1, max_length=64)
    unit: str = Field(default="unknown", max_length=32)
    limit: Optional[float] = Field(default=None, ge=0)
    remaining: Optional[float] = Field(default=None, ge=0)
    resets_at: Optional[datetime] = None
    source: str = Field(default="provider_reported", max_length=32)
    checked_at: Optional[datetime] = None
    ttl_seconds: int = Field(default=300, ge=10, le=86400)
    evidence: Dict[str, Any] = Field(default_factory=dict, max_length=50)


class ProviderHealthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(max_length=32)
    evidence: Dict[str, Any] = Field(default_factory=dict, max_length=50)
    ttl_seconds: int = Field(default=60, ge=10, le=3600)


class ProviderSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=16384)


@providers_router.get("")
async def list_provider_instances(db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await provider_registry_service.list(db)]


@providers_router.post("")
async def create_provider_instance(request: ProviderCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await provider_registry_service.create(db, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.patch("/{provider_id}")
async def update_provider_instance(provider_id: str, request: ProviderUpdateRequest, db: AsyncSession = Depends(get_db)):
    values = request.model_dump(exclude_unset=True)
    revision = values.pop("expected_revision")
    try:
        return (await provider_registry_service.update(db, provider_id, values, revision)).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.delete("/{provider_id}")
async def archive_provider_instance(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await provider_registry_service.remove(db, provider_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.get("/{provider_id}/quota")
async def get_provider_quota(provider_id: str, db: AsyncSession = Depends(get_db)):
    return [record.to_dict() for record in await quota_service.current(db, provider_id)]


@providers_router.post("/{provider_id}/quota")
async def record_provider_quota(provider_id: str, request: ProviderQuotaRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await quota_service.record(db, provider_id, request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.post("/{provider_id}/models/ingest")
async def ingest_provider_models(provider_id: str, request: ProviderModelIngestRequest, db: AsyncSession = Depends(get_db)):
    try:
        records = await provider_registry_service.ingest_models(db, provider_id, [item.model_dump() for item in request.models], request.ttl_seconds)
        return [record.to_dict() for record in records]
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.post("/{provider_id}/health")
async def record_provider_health(provider_id: str, request: ProviderHealthRequest, db: AsyncSession = Depends(get_db)):
    try:
        return (await provider_registry_service.record_health(db, provider_id, **request.model_dump())).to_dict()
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.get("/{provider_id}/health")
async def get_provider_health(provider_id: str, db: AsyncSession = Depends(get_db)):
    record = await db.get(ProviderInstanceRecord, provider_id)
    if not record:
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider instance was not found."})
    return provider_registry_service.assess_health(record)


@providers_router.get("/{provider_id}/secrets")
async def list_provider_secrets(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await provider_registry_service.list_secrets(db, provider_id)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.put("/{provider_id}/secrets")
async def set_provider_secret(provider_id: str, request: ProviderSecretRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await provider_registry_service.set_secret(db, provider_id, request.reference, request.value)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@providers_router.delete("/{provider_id}/secrets/{reference}")
async def delete_provider_secret(provider_id: str, reference: str, db: AsyncSession = Depends(get_db)):
    try:
        return await provider_registry_service.delete_secret(db, provider_id, reference)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


# --- Legacy Secrets Router ---
secrets_router = APIRouter(prefix="/api/secrets", tags=["Legacy Secrets"])


class SetSecretRequest(BaseModel):
    provider: str
    key_value: str


@secrets_router.get("")
async def get_secrets_status():
    return secret_vault.list_configured_providers()


@secrets_router.post("")
async def set_secret(req: SetSecretRequest):
    provider = req.provider.lower().strip()
    key_value = req.key_value.strip()
    if not key_value:
        raise HTTPException(status_code=400, detail="Credential cannot be empty.")

    test_requests = {
        "openai": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key_value}"}),
        "anthropic": ("https://api.anthropic.com/v1/models", {"x-api-key": key_value, "anthropic-version": "2023-06-01"}),
        "google": (f"https://generativelanguage.googleapis.com/v1beta/models?key={key_value}", {}),
        "groq": ("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key_value}"}),
        "deepseek": ("https://api.deepseek.com/models", {"Authorization": f"Bearer {key_value}"}),
    }
    if provider == "ollama_host":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{key_value.rstrip('/')}/api/tags")
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Ollama host did not return a healthy response.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not reach this Ollama host.") from exc
    elif provider in test_requests:
        url, headers = test_requests[provider]
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"{provider.title()} rejected this credential ({response.status_code}).")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not verify {provider.title()} right now.") from exc
    else:
        raise HTTPException(status_code=501, detail=f"Live validation and execution for {provider} are not implemented yet.")

    secret_vault.set_key(req.provider, req.key_value)
    return {"status": "verified_and_saved", "provider": req.provider}


@secrets_router.delete("/{provider}")
async def delete_secret(provider: str):
    secret_vault.delete_key(provider)
    return {"status": "deleted", "provider": provider}
