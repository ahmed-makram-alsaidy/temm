"""Database Models for AI Fleet OS."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ProviderInstanceRecord(Base):
    __tablename__ = "provider_instances"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    adapter_id = Column(String(128), nullable=False, index=True)
    protocol_version = Column(String(32), default="1.0")
    capabilities = Column(Text, default="[]")
    configuration = Column(Text, default="{}")
    secret_refs = Column(Text, default="[]")
    lifecycle_status = Column(String(32), default="active")
    user_enabled = Column(Boolean, default=True)
    health_state = Column(String(32), default="unknown")
    health_evidence = Column(Text, default="{}")
    health_checked_at = Column(DateTime, nullable=True)
    health_expires_at = Column(DateTime, nullable=True)
    revision = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "adapter_id": self.adapter_id,
            "protocol_version": self.protocol_version,
            "capabilities": json.loads(self.capabilities) if isinstance(self.capabilities, str) else self.capabilities,
            "configuration": json.loads(self.configuration) if isinstance(self.configuration, str) else self.configuration,
            "secret_refs": json.loads(self.secret_refs) if isinstance(self.secret_refs, str) else self.secret_refs,
            "lifecycle_status": self.lifecycle_status,
            "user_enabled": self.user_enabled,
            "health_state": self.health_state,
            "health_evidence": json.loads(self.health_evidence) if isinstance(self.health_evidence, str) else self.health_evidence,
            "health_checked_at": self.health_checked_at.isoformat() if self.health_checked_at else None,
            "health_expires_at": self.health_expires_at.isoformat() if self.health_expires_at else None,
            "revision": self.revision,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ModelRecord(Base):
    """Model Registry representing an LLM or API model."""
    __tablename__ = "models"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    provider = Column(String(64), nullable=False)  # openai, anthropic, google, alibaba, deepseek, mistral, groq, ollama, custom
    category = Column(String(64), default="general")  # coding, reasoning, general, fast, vision, arabic
    modalities = Column(Text, default="[\"text\"]")  # JSON list: text, vision, audio, code
    
    # Pricing per 1M tokens in USD
    input_cost_per_m = Column(Float, nullable=True)
    output_cost_per_m = Column(Float, nullable=True)
    cache_cost_per_m = Column(Float, nullable=True)
    reasoning_cost_per_m = Column(Float, nullable=True)
    
    context_window = Column(Integer, default=128000)
    is_local = Column(Boolean, default=False)
    is_free = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_reference_baseline = Column(Boolean, default=False)

    registry_state = Column(String(32), default="catalog")
    lifecycle_status = Column(String(32), default="active")
    availability_state = Column(String(32), default="unknown")
    availability_evidence = Column(Text, default="{}")
    availability_checked_at = Column(DateTime, nullable=True)
    availability_expires_at = Column(DateTime, nullable=True)
    source_type = Column(String(32), default="catalog")
    source_uri = Column(String(1024), default="")
    source_checked_at = Column(DateTime, nullable=True)
    metadata_provenance = Column(String(32), default="unverified")
    pricing_provenance = Column(String(32), default="unknown")
    capability_provenance = Column(String(32), default="unknown")
    pricing_currency = Column(String(8), default="USD")
    pricing_effective_at = Column(DateTime, nullable=True)
    revision = Column(Integer, default=1)

    # Legacy catalog score fields; truth metadata determines whether they are usable evidence. (0 - 100)
    quality_score = Column(Float, nullable=True)
    coding_score = Column(Float, nullable=True)
    reasoning_score = Column(Float, nullable=True)
    arabic_score = Column(Float, nullable=True)
    vision_score = Column(Float, nullable=True)
    speed_score = Column(Float, nullable=True)
    reliability_score = Column(Float, nullable=True)
    tokens_per_sec = Column(Float, nullable=True)
    
    # Metadata
    best_for = Column(Text, default="[\"General Tasks\"]")  # JSON list
    not_ideal_for = Column(Text, default="[]")  # JSON list
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "category": self.category,
            "modalities": json.loads(self.modalities) if isinstance(self.modalities, str) else self.modalities,
            "input_cost_per_m": self.input_cost_per_m,
            "output_cost_per_m": self.output_cost_per_m,
            "cache_cost_per_m": self.cache_cost_per_m,
            "reasoning_cost_per_m": self.reasoning_cost_per_m,
            "context_window": self.context_window,
            "is_local": self.is_local,
            "is_free": self.is_free,
            "is_active": self.is_active,
            "is_reference_baseline": self.is_reference_baseline,
            "registry_state": self.registry_state,
            "lifecycle_status": self.lifecycle_status,
            "availability_state": self.availability_state,
            "availability_evidence": json.loads(self.availability_evidence) if isinstance(self.availability_evidence, str) else self.availability_evidence,
            "availability_checked_at": self.availability_checked_at.isoformat() if self.availability_checked_at else None,
            "availability_expires_at": self.availability_expires_at.isoformat() if self.availability_expires_at else None,
            "source_type": self.source_type,
            "source_uri": self.source_uri,
            "source_checked_at": self.source_checked_at.isoformat() if self.source_checked_at else None,
            "metadata_provenance": self.metadata_provenance,
            "pricing_provenance": self.pricing_provenance,
            "capability_provenance": self.capability_provenance,
            "pricing_currency": self.pricing_currency,
            "pricing_effective_at": self.pricing_effective_at.isoformat() if self.pricing_effective_at else None,
            "revision": self.revision,
            "quality_score": self.quality_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "coding_score": self.coding_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "reasoning_score": self.reasoning_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "arabic_score": self.arabic_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "vision_score": self.vision_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "speed_score": self.speed_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "reliability_score": self.reliability_score if self.capability_provenance in {"measured", "provider_reported"} else None,
            "tokens_per_sec": self.tokens_per_sec if self.capability_provenance in {"measured", "provider_reported"} else None,
            "best_for": json.loads(self.best_for) if isinstance(self.best_for, str) else self.best_for,
            "not_ideal_for": json.loads(self.not_ideal_for) if isinstance(self.not_ideal_for, str) else self.not_ideal_for,
            "description": self.description,
        }


class ModelCapabilityEvidenceRecord(Base):
    __tablename__ = "model_capability_evidence"

    id = Column(String(64), primary_key=True)
    model_id = Column(String(64), ForeignKey("models.id"), nullable=False, index=True)
    capability = Column(String(64), nullable=False, index=True)
    supported = Column(Boolean, nullable=False)
    score = Column(Float, nullable=True)
    provenance = Column(String(32), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_uri = Column(String(1024), default="")
    evidence = Column(Text, default="{}")
    observed_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "capability": self.capability,
            "supported": self.supported,
            "score": self.score,
            "provenance": self.provenance,
            "source_type": self.source_type,
            "source_uri": self.source_uri,
            "evidence": json.loads(self.evidence) if isinstance(self.evidence, str) else self.evidence,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class ModelPriceRecord(Base):
    __tablename__ = "model_prices"

    id = Column(String(64), primary_key=True)
    model_id = Column(String(64), ForeignKey("models.id"), nullable=False, index=True)
    currency = Column(String(8), nullable=False, default="USD")
    input_per_m = Column(Float, nullable=True)
    output_per_m = Column(Float, nullable=True)
    cache_per_m = Column(Float, nullable=True)
    reasoning_per_m = Column(Float, nullable=True)
    source_type = Column(String(32), nullable=False)
    source_uri = Column(String(1024), default="")
    provenance = Column(String(32), nullable=False)
    confidence = Column(String(16), default="unknown")
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "currency": self.currency,
            "input_per_m": self.input_per_m,
            "output_per_m": self.output_per_m,
            "cache_per_m": self.cache_per_m,
            "reasoning_per_m": self.reasoning_per_m,
            "source_type": self.source_type,
            "source_uri": self.source_uri,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class AgentRecord(Base):
    """Agent Registry representing a CLI or Runtime with tool capabilities."""
    __tablename__ = "agents"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    cli_command = Column(String(256), nullable=False)
    version_command = Column(String(128), default="")
    prompt_arg_format = Column(String(256), default="{prompt}")
    workspace_arg_format = Column(String(256), default="--workspace {workspace}")
    input_method = Column(String(32), default="argument")
    output_method = Column(String(32), default="stdout")
    supports_pty = Column(Boolean, default=False)
    supports_interactive = Column(Boolean, default=False)
    capabilities = Column(Text, default="[]")
    tool_kind = Column(String(32), default="agent")
    adapter_id = Column(String(128), default="")
    discovery_state = Column(String(32), default="unavailable")
    discovery_source = Column(String(32), default="manifest")
    discovery_evidence = Column(Text, default="{}")
    version_probe_args = Column(Text, default="[]")
    health_probe_args = Column(Text, default="[]")
    invocation_args = Column(Text, default="[]")
    environment_refs = Column(Text, default="[]")
    secret_refs = Column(Text, default="[]")
    working_directory = Column(String(32), default="workspace")
    probe_timeout_seconds = Column(Float, default=3.0)
    permission_profile = Column(String(32), default="developer")
    user_enabled = Column(Boolean, default=True)
    lifecycle_status = Column(String(32), default="active")
    revision = Column(Integer, default=1)
    auth_state = Column(String(32), default="unknown")
    auth_method = Column(String(64), default="unknown")
    auth_evidence = Column(Text, default="{}")
    auth_checked_at = Column(DateTime, nullable=True)
    auth_setup_action = Column(Text, default="{}")
    auth_probe_args = Column(Text, default="[]")
    auth_probe_parser = Column(Text, default="{}")
    is_installed = Column(Boolean, default=False)
    detected_path = Column(String(1024), default="")
    version = Column(String(128), default="")
    status = Column(String(32), default="unavailable")
    last_checked_at = Column(DateTime, nullable=True)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        execution_ready = (
            self.tool_kind == "agent"
            and bool(self.user_enabled)
            and self.lifecycle_status == "active"
            and self.discovery_state == "verified"
            and self.status == "ready"
            and self.auth_state in {"not_required", "verified"}
            and bool(self.detected_path or self.cli_command)
        )
        return {
            "id": self.id,
            "name": self.name,
            "cli_command": self.cli_command,
            "version_command": self.version_command,
            "prompt_arg_format": self.prompt_arg_format,
            "workspace_arg_format": self.workspace_arg_format,
            "input_method": self.input_method,
            "output_method": self.output_method,
            "supports_pty": self.supports_pty,
            "supports_interactive": self.supports_interactive,
            "capabilities": json.loads(self.capabilities) if isinstance(self.capabilities, str) else self.capabilities,
            "tool_kind": self.tool_kind,
            "adapter_id": self.adapter_id,
            "discovery_state": self.discovery_state,
            "discovery_source": self.discovery_source,
            "discovery_evidence": json.loads(self.discovery_evidence) if isinstance(self.discovery_evidence, str) else self.discovery_evidence,
            "version_probe_args": json.loads(self.version_probe_args) if isinstance(self.version_probe_args, str) else self.version_probe_args,
            "health_probe_args": json.loads(self.health_probe_args) if isinstance(self.health_probe_args, str) else self.health_probe_args,
            "invocation_args": json.loads(self.invocation_args) if isinstance(self.invocation_args, str) else self.invocation_args,
            "environment_refs": json.loads(self.environment_refs) if isinstance(self.environment_refs, str) else self.environment_refs,
            "secret_refs": json.loads(self.secret_refs) if isinstance(self.secret_refs, str) else self.secret_refs,
            "working_directory": self.working_directory,
            "probe_timeout_seconds": self.probe_timeout_seconds,
            "permission_profile": self.permission_profile,
            "user_enabled": self.user_enabled,
            "lifecycle_status": self.lifecycle_status,
            "revision": self.revision,
            "auth_state": self.auth_state,
            "auth_method": self.auth_method,
            "auth_evidence": json.loads(self.auth_evidence) if isinstance(self.auth_evidence, str) else self.auth_evidence,
            "auth_checked_at": self.auth_checked_at.isoformat() if self.auth_checked_at else None,
            "auth_setup_action": json.loads(self.auth_setup_action) if isinstance(self.auth_setup_action, str) else self.auth_setup_action,
            "auth_probe_args": json.loads(self.auth_probe_args) if isinstance(self.auth_probe_args, str) else self.auth_probe_args,
            "auth_probe_parser": json.loads(self.auth_probe_parser) if isinstance(self.auth_probe_parser, str) else self.auth_probe_parser,
            "is_installed": self.is_installed,
            "detected_path": self.detected_path,
            "version": self.version,
            "status": self.status,
            "execution_ready": execution_ready,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RunAttemptRecord(Base):
    __tablename__ = "run_attempts"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    executor_type = Column(String(32), nullable=False)
    agent_id = Column(String(64), nullable=True)
    model_id = Column(String(128), nullable=True)
    provider_instance_id = Column(String(64), nullable=True)
    status = Column(String(32), default="starting")
    outcome = Column(String(32), nullable=True)
    error_code = Column(String(128), nullable=True)
    receipt_json = Column(Text, default="{}")
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "attempt_number": self.attempt_number,
                "executor_type": self.executor_type, "agent_id": self.agent_id, "model_id": self.model_id,
                "provider_instance_id": self.provider_instance_id, "status": self.status, "outcome": self.outcome,
                "error_code": self.error_code,
                "receipt": json.loads(self.receipt_json) if isinstance(self.receipt_json, str) else self.receipt_json,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None}


class RunOutputChunkRecord(Base):
    __tablename__ = "run_output_chunks"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False, index=True)
    attempt_id = Column(String(64), ForeignKey("run_attempts.id"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False)
    stream = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    byte_count = Column(Integer, nullable=False)
    truncated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "attempt_id": self.attempt_id,
                "sequence": self.sequence, "stream": self.stream, "content": self.content,
                "byte_count": self.byte_count, "truncated": self.truncated,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class RunArtifactRecord(Base):
    __tablename__ = "run_artifacts"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False, index=True)
    attempt_id = Column(String(64), ForeignKey("run_attempts.id"), nullable=True, index=True)
    artifact_type = Column(String(32), nullable=False)
    path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "attempt_id": self.attempt_id,
                "artifact_type": self.artifact_type, "path": self.path, "sha256": self.sha256,
                "metadata": json.loads(self.metadata_json) if isinstance(self.metadata_json, str) else self.metadata_json,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class TaskRun(Base):
    """Execution Task Run record with metrics, costs, savings, and logs."""
    __tablename__ = "task_runs"

    id = Column(String(64), primary_key=True)
    prompt = Column(Text, nullable=False)
    task_type = Column(String(64), default="general")  # coding, reasoning, arabic, fast, vision, research
    selected_model_id = Column(String(64), nullable=True)
    selected_agent_id = Column(String(64), nullable=True)
    workspace_id = Column(String(64), nullable=True)
    project_id = Column(String(64), nullable=True)
    workflow_id = Column(String(64), nullable=True)
    current_attempt_id = Column(String(64), nullable=True)
    status_reason = Column(String(128), nullable=True)
    cancellation_requested_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    revision = Column(Integer, default=1)
    routing_mode = Column(String(32), default="balanced")  # economy, quality, balanced, fast, custom
    status = Column(String(32), default="running")  # running, completed, failed, cancelled
    
    # Financials & Tokens
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    actual_cost = Column(Float, default=0.0)
    reference_cost = Column(Float, default=0.0)
    saved_amount = Column(Float, default=0.0)
    saving_percentage = Column(Float, default=0.0)
    
    duration_ms = Column(Integer, default=0)
    quality_eval_score = Column(Float, nullable=True)
    token_provenance = Column(String(32), default="unknown")
    cost_provenance = Column(String(32), default="unknown")
    quality_provenance = Column(String(32), default="unknown")
    latency_provenance = Column(String(32), default="measured")
    measurement_metadata = Column(Text, default="{}")
    financials_json = Column(Text, default="{}")

    route_explanation = Column(Text, default="")
    fallback_chain = Column(Text, default="[]")  # JSON list of models attempted
    log_output = Column(Text, default="")
    result_output = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "task_type": self.task_type,
            "selected_model_id": self.selected_model_id,
            "selected_agent_id": self.selected_agent_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "current_attempt_id": self.current_attempt_id,
            "status_reason": self.status_reason,
            "cancellation_requested_at": self.cancellation_requested_at.isoformat() if self.cancellation_requested_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "revision": self.revision,
            "routing_mode": self.routing_mode,
            "status": self.status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "actual_cost": round(self.actual_cost, 8) if self.actual_cost is not None and self.cost_provenance != "unknown" else None,
            "reference_cost": round(self.reference_cost, 8) if self.reference_cost is not None and self.cost_provenance != "unknown" else None,
            "saved_amount": round(self.saved_amount, 8) if self.saved_amount is not None and self.cost_provenance != "unknown" else None,
            "saving_percentage": round(self.saving_percentage, 1) if self.saving_percentage is not None and self.cost_provenance != "unknown" else None,
            "duration_ms": self.duration_ms,
            "quality_eval_score": self.quality_eval_score,
            "token_provenance": self.token_provenance,
            "cost_provenance": self.cost_provenance,
            "quality_provenance": self.quality_provenance,
            "latency_provenance": self.latency_provenance,
            "measurement_metadata": json.loads(self.measurement_metadata) if isinstance(self.measurement_metadata, str) else self.measurement_metadata,
            "financials": json.loads(self.financials_json) if isinstance(self.financials_json, str) else (self.financials_json or {}),
            "route_explanation": self.route_explanation,
            "fallback_chain": json.loads(self.fallback_chain) if isinstance(self.fallback_chain, str) else self.fallback_chain,
            "log_output": self.log_output,
            "result_output": self.result_output,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DeliverableRecord(Base):
    __tablename__ = "deliverables"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(256), nullable=False)
    component = Column(String(128), nullable=True)
    version = Column(String(64), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    checksum = Column(String(64), nullable=False)
    readiness = Column(String(32), nullable=False)
    requirement_ids_json = Column(Text, nullable=False, default="[]")
    asset_ids_json = Column(Text, nullable=False, default="[]")
    run_ids_json = Column(Text, nullable=False, default="[]")
    gate_ids_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "workspace_id": self.workspace_id,
                "name": self.name, "component": self.component, "version": self.version,
                "relative_path": self.relative_path, "checksum": self.checksum, "readiness": self.readiness,
                "requirement_ids": json.loads(self.requirement_ids_json), "asset_ids": json.loads(self.asset_ids_json),
                "run_ids": json.loads(self.run_ids_json), "gate_ids": json.loads(self.gate_ids_json),
                "created_at": self.created_at.isoformat() if self.created_at else None}


class OrchestrationCheckpointRecord(Base):
    __tablename__ = "orchestration_checkpoints"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    state = Column(String(32), nullable=False)
    cursor_json = Column(Text, nullable=False, default="{}")
    ready_queue_json = Column(Text, nullable=False, default="[]")
    active_task_ids_json = Column(Text, nullable=False, default="[]")
    lock_keys_json = Column(Text, nullable=False, default="[]")
    revision = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "state": self.state,
                "cursor": json.loads(self.cursor_json), "ready_queue": json.loads(self.ready_queue_json),
                "active_task_ids": json.loads(self.active_task_ids_json), "lock_keys": json.loads(self.lock_keys_json),
                "revision": self.revision, "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class QualityWaiverRecord(Base):
    __tablename__ = "quality_waivers"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    finding_id = Column(String(128), nullable=False, index=True)
    scope_type = Column(String(32), nullable=False)
    scope_id = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)
    risk = Column(Text, nullable=False)
    owner = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "finding_id": self.finding_id,
                "scope_type": self.scope_type, "scope_id": self.scope_id, "reason": self.reason,
                "risk": self.risk, "owner": self.owner, "expires_at": self.expires_at.isoformat(),
                "status": self.status, "finding_status": "waived", "passed": False,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class AcceptanceCriterionRecord(Base):
    __tablename__ = "acceptance_criteria"

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("orchestration_tasks.id"), nullable=False, index=True)
    criterion_type = Column(String(32), nullable=False)
    description = Column(Text, nullable=False)
    evaluator = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    evidence_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="pending")
    waiver_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "task_id": self.task_id, "criterion_type": self.criterion_type,
                "description": self.description, "evaluator": self.evaluator, "severity": self.severity,
                "evidence": json.loads(self.evidence_json), "status": self.status,
                "waiver": json.loads(self.waiver_json) if self.waiver_json else None,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class OrchestrationTaskRecord(Base):
    __tablename__ = "orchestration_tasks"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    task_type = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    requirement_ids_json = Column(Text, nullable=False, default="[]")
    dependency_ids_json = Column(Text, nullable=False, default="[]")
    acceptance_json = Column(Text, nullable=False, default="[]")
    context_refs_json = Column(Text, nullable=False, default="[]")
    executor_needs_json = Column(Text, nullable=False, default="{}")
    state = Column(String(32), nullable=False, default="planned")
    current_run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "task_type": self.task_type,
                "title": self.title, "description": self.description,
                "requirement_ids": json.loads(self.requirement_ids_json),
                "dependency_ids": json.loads(self.dependency_ids_json),
                "acceptance": json.loads(self.acceptance_json),
                "context_refs": json.loads(self.context_refs_json),
                "executor_needs": json.loads(self.executor_needs_json), "state": self.state,
                "current_run_id": self.current_run_id, "revision": self.revision,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class AssetCollectionRecord(Base):
    __tablename__ = "asset_collections"

    id = Column(String(64), primary_key=True)
    name = Column(String(256), nullable=False)
    owner = Column(String(128), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "owner": self.owner, "description": self.description,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class AssetCollectionMemberRecord(Base):
    __tablename__ = "asset_collection_members"

    id = Column(String(64), primary_key=True)
    collection_id = Column(String(64), ForeignKey("asset_collections.id"), nullable=False, index=True)
    asset_id = Column(String(64), ForeignKey("assets.id"), nullable=False, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "collection_id": self.collection_id, "asset_id": self.asset_id,
                "added_at": self.added_at.isoformat() if self.added_at else None}


class AssetCollectionProjectLinkRecord(Base):
    __tablename__ = "asset_collection_project_links"

    id = Column(String(64), primary_key=True)
    collection_id = Column(String(64), ForeignKey("asset_collections.id"), nullable=False, index=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    linked_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "collection_id": self.collection_id, "project_id": self.project_id,
                "linked_at": self.linked_at.isoformat() if self.linked_at else None}


class AssetTransformJobRecord(Base):
    __tablename__="asset_transform_jobs"
    id=Column(String(64),primary_key=True);run_id=Column(String(64),ForeignKey("task_runs.id"),nullable=True,index=True);original_asset_id=Column(String(64),ForeignKey("assets.id"),nullable=False,index=True);derivative_asset_id=Column(String(64),ForeignKey("assets.id"),nullable=True,index=True);tool=Column(String(128),nullable=False);tool_version=Column(String(64),nullable=False);parameters_json=Column(Text,nullable=False);status=Column(String(32),nullable=False);input_hash=Column(String(64),nullable=False);output_hash=Column(String(64),nullable=True);provenance=Column(String(32),nullable=False);created_at=Column(DateTime,default=datetime.utcnow);completed_at=Column(DateTime,nullable=True)
    def to_dict(self):return {"id":self.id,"run_id":self.run_id,"original_asset_id":self.original_asset_id,"derivative_asset_id":self.derivative_asset_id,"tool":self.tool,"tool_version":self.tool_version,"parameters":json.loads(self.parameters_json),"status":self.status,"input_hash":self.input_hash,"output_hash":self.output_hash,"provenance":self.provenance,"created_at":self.created_at.isoformat() if self.created_at else None,"completed_at":self.completed_at.isoformat() if self.completed_at else None}


class AssetLicenseRecord(Base):
    __tablename__="asset_licenses"
    id=Column(String(128),primary_key=True);name=Column(String(256),nullable=False);source_uri=Column(String(2048),nullable=True);restrictions_json=Column(Text,nullable=False,default="[]");confidence=Column(String(16),nullable=False);approval_status=Column(String(32),nullable=False,default="pending");approved_by=Column(String(128),nullable=True);created_at=Column(DateTime,default=datetime.utcnow)
    def to_dict(self):return {"id":self.id,"name":self.name,"source_uri":self.source_uri,"restrictions":json.loads(self.restrictions_json),"confidence":self.confidence,"approval_status":self.approval_status,"approved_by":self.approved_by,"commercially_safe":self.approval_status=="approved" and self.confidence in {"high","verified"},"created_at":self.created_at.isoformat() if self.created_at else None}


class AssetUsageRecord(Base):
    __tablename__="asset_usage"
    id=Column(String(64),primary_key=True); asset_id=Column(String(64),ForeignKey("assets.id"),nullable=False,index=True); target_type=Column(String(32),nullable=False); target_id=Column(String(128),nullable=False,index=True); usage_role=Column(String(64),nullable=False); required=Column(Boolean,nullable=False,default=True); created_at=Column(DateTime,default=datetime.utcnow)
    def to_dict(self):return {"id":self.id,"asset_id":self.asset_id,"target_type":self.target_type,"target_id":self.target_id,"usage_role":self.usage_role,"required":self.required,"created_at":self.created_at.isoformat() if self.created_at else None}


class ResearchClaimRecord(Base):
    __tablename__ = "research_claims"
    id=Column(String(64),primary_key=True); query_id=Column(String(64),ForeignKey("research_queries.id"),nullable=False,index=True); project_id=Column(String(64),ForeignKey("projects.id"),nullable=False,index=True); requirement_id=Column(String(64),ForeignKey("project_requirements.id"),nullable=True); statement=Column(Text,nullable=False); status=Column(String(32),nullable=False,default="unsupported"); created_at=Column(DateTime,default=datetime.utcnow)
    def to_dict(self): return {"id":self.id,"query_id":self.query_id,"project_id":self.project_id,"requirement_id":self.requirement_id,"statement":self.statement,"status":self.status,"created_at":self.created_at.isoformat() if self.created_at else None}

class ResearchCitationRecord(Base):
    __tablename__ = "research_citations"
    id=Column(String(64),primary_key=True); claim_id=Column(String(64),ForeignKey("research_claims.id"),nullable=False,index=True); source_id=Column(String(64),ForeignKey("research_sources.id"),nullable=False,index=True); excerpt=Column(Text,nullable=False); excerpt_hash=Column(String(64),nullable=False); locator=Column(String(256),nullable=True); created_at=Column(DateTime,default=datetime.utcnow)
    def to_dict(self): return {"id":self.id,"claim_id":self.claim_id,"source_id":self.source_id,"excerpt":self.excerpt,"excerpt_hash":self.excerpt_hash,"locator":self.locator,"created_at":self.created_at.isoformat() if self.created_at else None}


class ResearchSourceRecord(Base):
    __tablename__ = "research_sources"
    id=Column(String(64),primary_key=True); query_id=Column(String(64),ForeignKey("research_queries.id"),nullable=False,index=True); url=Column(String(2048),nullable=False); title=Column(String(512),nullable=False); source_type=Column(String(64),nullable=False); author=Column(String(256),nullable=True); retrieved_at=Column(DateTime,nullable=False); freshness_at=Column(DateTime,nullable=True); content_hash=Column(String(64),nullable=False); version=Column(Integer,nullable=False); license_id=Column(String(128),nullable=True); confidence=Column(Float,nullable=True); metadata_json=Column(Text,nullable=False,default="{}")
    def to_dict(self): return {"id":self.id,"query_id":self.query_id,"url":self.url,"title":self.title,"source_type":self.source_type,"author":self.author,"retrieved_at":self.retrieved_at.isoformat(),"freshness_at":self.freshness_at.isoformat() if self.freshness_at else None,"content_hash":self.content_hash,"version":self.version,"license_id":self.license_id,"confidence":self.confidence,"metadata":json.loads(self.metadata_json)}


class AssetRecord(Base):
    __tablename__ = "assets"
    id = Column(String(64), primary_key=True)
    scope_type = Column(String(32), nullable=False)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=True, index=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id"), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    asset_type = Column(String(32), nullable=True)
    mime_type = Column(String(128), nullable=True)
    sha256 = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    provenance = Column(String(32), nullable=False)
    license_id = Column(String(128), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    state = Column(String(32), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    def to_dict(self): return {"id":self.id,"scope_type":self.scope_type,"project_id":self.project_id,"workspace_id":self.workspace_id,"relative_path":self.relative_path,"asset_type":self.asset_type,"mime_type":self.mime_type,"sha256":self.sha256,"source_type":self.source_type,"source_id":self.source_id,"provenance":self.provenance,"license_id":self.license_id,"width":self.width,"height":self.height,"duration_ms":self.duration_ms,"size_bytes":self.size_bytes,"state":self.state,"metadata":json.loads(self.metadata_json),"created_at":self.created_at.isoformat() if self.created_at else None}


class ResearchQueryRecord(Base):
    __tablename__ = "research_queries"
    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    query_kind = Column(String(32), nullable=False)
    freshness_after = Column(DateTime, nullable=True)
    source_policy_json = Column(Text, nullable=False)
    claim_ids_json = Column(Text, nullable=False, default="[]")
    project_usage_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    def to_dict(self):
        return {"id":self.id,"project_id":self.project_id,"question":self.question,"query_kind":self.query_kind,"freshness_after":self.freshness_after.isoformat() if self.freshness_after else None,"source_policy":json.loads(self.source_policy_json),"claim_ids":json.loads(self.claim_ids_json),"project_usage":json.loads(self.project_usage_json),"status":self.status,"created_at":self.created_at.isoformat() if self.created_at else None,"updated_at":self.updated_at.isoformat() if self.updated_at else None}


class ContextPackRecord(Base):
    __tablename__ = "context_packs"
    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=True, index=True)
    run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=True, index=True)
    manifest_json = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    token_provenance = Column(String(32), nullable=False)
    token_method = Column(String(128), nullable=True)
    redactions_json = Column(Text, nullable=False, default="[]")
    generated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id":self.id,"project_id":self.project_id,"run_id":self.run_id,"manifest":json.loads(self.manifest_json),"token_count":self.token_count,"token_provenance":self.token_provenance,"token_method":self.token_method,"redactions":json.loads(self.redactions_json),"generated_at":self.generated_at.isoformat() if self.generated_at else None}


class ProjectLearningConsentRecord(Base):
    __tablename__ = "project_learning_consent"
    project_id = Column(String(64), ForeignKey("projects.id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    granted_by = Column(String(128), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectOutcomeRecord(Base):
    __tablename__ = "project_outcomes"
    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    run_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False, unique=True)
    task_category = Column(String(64), nullable=False)
    route_id = Column(String(256), nullable=False)
    outcome = Column(String(32), nullable=False)
    preferred = Column(Boolean, nullable=False)
    evidence_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectNeedRecord(Base):
    __tablename__ = "project_needs"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    requirement_id = Column(String(64), ForeignKey("project_requirements.id"), nullable=True, index=True)
    need_type = Column(String(32), nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    impact = Column(String(32), nullable=False)
    blocked_nodes_json = Column(Text, nullable=False, default="[]")
    state = Column(String(32), nullable=False, default="open")
    resolution_json = Column(Text, nullable=True)
    dedupe_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "requirement_id": self.requirement_id,
                "need_type": self.need_type, "title": self.title, "description": self.description,
                "source_type": self.source_type, "source_id": self.source_id, "impact": self.impact,
                "blocked_nodes": json.loads(self.blocked_nodes_json), "state": self.state,
                "resolution": json.loads(self.resolution_json) if self.resolution_json else None,
                "dedupe_key": self.dedupe_key, "created_at": self.created_at.isoformat() if self.created_at else None,
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None}


class BlueprintProposalRecord(Base):
    __tablename__ = "blueprint_proposals"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    template_id = Column(String(128), nullable=False)
    template_version = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="proposed")
    content_json = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    approved_by = Column(String(128), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "template_id": self.template_id,
                "template_version": self.template_version, "status": self.status,
                "content": json.loads(self.content_json), "revision": self.revision,
                "approved_by": self.approved_by, "approved_at": self.approved_at.isoformat() if self.approved_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class BlueprintProposalRevisionRecord(Base):
    __tablename__ = "blueprint_proposal_revisions"
    id = Column(String(64), primary_key=True)
    proposal_id = Column(String(64), ForeignKey("blueprint_proposals.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectRequirementRecord(Base):
    __tablename__ = "project_requirements"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    parent_id = Column(String(64), ForeignKey("project_requirements.id"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    requirement_type = Column(String(32), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    truth_state = Column(String(32), nullable=False)
    priority = Column(String(16), nullable=False)
    status = Column(String(32), nullable=False)
    acceptance_json = Column(Text, nullable=False, default="[]")
    evidence_json = Column(Text, nullable=False, default="[]")
    owner = Column(String(128), nullable=True)
    waiver_rationale = Column(Text, nullable=True)
    waived_by = Column(String(128), nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "parent_id": self.parent_id,
                "title": self.title, "description": self.description, "requirement_type": self.requirement_type,
                "source_type": self.source_type, "source_id": self.source_id, "truth_state": self.truth_state,
                "priority": self.priority, "status": self.status, "acceptance": json.loads(self.acceptance_json),
                "evidence": json.loads(self.evidence_json), "owner": self.owner,
                "waiver_rationale": self.waiver_rationale, "waived_by": self.waived_by, "revision": self.revision,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class ProjectRequirementEdgeRecord(Base):
    __tablename__ = "project_requirement_edges"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    source_id = Column(String(64), ForeignKey("project_requirements.id"), nullable=False, index=True)
    target_id = Column(String(64), ForeignKey("project_requirements.id"), nullable=False, index=True)
    edge_type = Column(String(32), nullable=False)
    rationale = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "source_id": self.source_id,
                "target_id": self.target_id, "edge_type": self.edge_type, "rationale": self.rationale,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class ProjectRequirementRevisionRecord(Base):
    __tablename__ = "project_requirement_revisions"

    id = Column(String(64), primary_key=True)
    requirement_id = Column(String(64), ForeignKey("project_requirements.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectDecisionRecord(Base):
    __tablename__ = "project_decisions"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    scope_type = Column(String(32), nullable=False)
    scope_id = Column(String(128), nullable=True)
    statement = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    impact = Column(Text, nullable=False)
    rule_json = Column(Text, nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="proposed")
    supersedes_id = Column(String(64), ForeignKey("project_decisions.id"), nullable=True)
    approved_by = Column(String(128), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "scope_type": self.scope_type,
                "scope_id": self.scope_id, "statement": self.statement, "rationale": self.rationale,
                "impact": self.impact, "rule": json.loads(self.rule_json), "source_type": self.source_type,
                "source_id": self.source_id, "status": self.status, "supersedes_id": self.supersedes_id,
                "approved_by": self.approved_by, "approved_at": self.approved_at.isoformat() if self.approved_at else None,
                "revision": self.revision, "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class ProjectDecisionRevisionRecord(Base):
    __tablename__ = "project_decision_revisions"

    id = Column(String(64), primary_key=True)
    decision_id = Column(String(64), ForeignKey("project_decisions.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectBrainFactRecord(Base):
    __tablename__ = "project_brain_facts"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    section = Column(String(64), nullable=False)
    fact_key = Column(String(128), nullable=False)
    value_json = Column(Text, nullable=False)
    truth_state = Column(String(32), nullable=False)
    provenance = Column(String(32), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    confidence = Column(Float, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "section": self.section, "fact_key": self.fact_key,
                "value": json.loads(self.value_json), "truth_state": self.truth_state, "provenance": self.provenance,
                "source_type": self.source_type, "source_id": self.source_id, "confidence": self.confidence,
                "revision": self.revision, "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class ProjectBrainFactRevisionRecord(Base):
    __tablename__ = "project_brain_fact_revisions"

    id = Column(String(64), primary_key=True)
    fact_id = Column(String(64), ForeignKey("project_brain_facts.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectRecord(Base):
    __tablename__ = "projects"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    purpose = Column(Text, default="")
    project_type = Column(String(64), nullable=False)
    owner = Column(String(128), nullable=False)
    lifecycle_status = Column(String(32), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "slug": self.slug, "purpose": self.purpose,
                "project_type": self.project_type, "owner": self.owner,
                "lifecycle_status": self.lifecycle_status, "revision": self.revision,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class ProjectWorkspaceLinkRecord(Base):
    __tablename__ = "project_workspace_links"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="primary")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "project_id": self.project_id, "workspace_id": self.workspace_id,
                "role": self.role, "created_at": self.created_at.isoformat() if self.created_at else None}


class WorkspaceRecord(Base):
    """An explicitly approved folder boundary for agents and commands."""
    __tablename__ = "workspaces"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    path = Column(String(1024), nullable=False, unique=True)
    permission_profile = Column(String(32), default="developer")
    allowed_shells = Column(Text, default='["powershell"]')
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "permission_profile": self.permission_profile,
            "allowed_shells": json.loads(self.allowed_shells) if isinstance(self.allowed_shells, str) else self.allowed_shells,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


class CommandRunRecord(Base):
    """Auditable command execution confined to an approved workspace."""
    __tablename__ = "command_runs"

    id = Column(String(64), primary_key=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id"), nullable=False)
    command = Column(Text, nullable=False)
    shell = Column(String(32), default="powershell")
    status = Column(String(32), default="running")
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, default="")
    stderr = Column(Text, default="")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "command": self.command,
            "shell": self.shell,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PluginCatalogSourceRecord(Base):
    __tablename__ = "plugin_catalog_sources"

    id = Column(String(128), primary_key=True)
    index_url = Column(String(1024), nullable=False, unique=True)
    public_key = Column(Text, nullable=False)
    enabled = Column(Boolean, default=False)
    last_state = Column(String(32), default="never_refreshed")
    last_error = Column(Text, default="")
    catalog_json = Column(Text, default="{}")
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        catalog = json.loads(self.catalog_json) if self.catalog_json else {}
        return {
            "id": self.id,
            "index_url": self.index_url,
            "enabled": self.enabled,
            "last_state": self.last_state,
            "last_error": self.last_error,
            "entry_count": len(catalog.get("entries", [])),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PluginRecord(Base):
    """Registered local plugin package metadata; plugin code is never trusted on inspection."""
    __tablename__ = "plugins"

    id = Column(String(128), primary_key=True)
    name = Column(String(160), nullable=False)
    path = Column(String(1024), nullable=False, unique=True)
    version = Column(String(64), default="0.1.0")
    protocol_version = Column(String(32), default="1.x")
    plugin_type = Column(String(64), default="cli")
    status = Column(String(32), default="registered")
    manifest = Column(Text, default="{}")
    permissions = Column(Text, default="[]")
    granted_permissions = Column(Text, default="[]")
    permission_profile = Column(String(32), default="safe")
    package_hash = Column(String(64), default="")
    entrypoint = Column(String(1024), default="")
    load_state = Column(String(32), default="registered")
    source_type = Column(String(32), default="local")
    source_id = Column(String(128), nullable=True)
    source_package_url = Column(String(1024), nullable=True)
    previous_path = Column(String(1024), nullable=True)
    previous_hash = Column(String(64), nullable=True)
    installed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "plugin_type": self.plugin_type,
            "status": self.status,
            "manifest": json.loads(self.manifest) if isinstance(self.manifest, str) else self.manifest,
            "permissions": json.loads(self.permissions) if isinstance(self.permissions, str) else self.permissions,
            "granted_permissions": json.loads(self.granted_permissions) if isinstance(self.granted_permissions, str) else self.granted_permissions,
            "permission_profile": self.permission_profile,
            "package_hash": self.package_hash,
            "entrypoint": self.entrypoint,
            "load_state": self.load_state,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_package_url": self.source_package_url,
            "previous_hash": self.previous_hash,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ChatSession(Base):
    """Conversational Studio Chat Session."""
    __tablename__ = "chat_sessions"

    id = Column(String(64), primary_key=True)
    title = Column(String(256), default="New AI Fleet Chat")
    model_id = Column(String(64), default="auto")  # 'auto' or specific model ID
    routing_mode = Column(String(32), default="balanced")
    total_tokens = Column(Integer, default=0)
    total_saved = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "model_id": self.model_id,
            "routing_mode": self.routing_mode,
            "total_tokens": self.total_tokens,
            "total_saved": round(self.total_saved, 4),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Base):
    """Message inside a Chat Session."""
    __tablename__ = "chat_messages"

    id = Column(String(64), primary_key=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.id"))
    role = Column(String(16), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    model_used = Column(String(64), nullable=True)
    provider_used = Column(String(64), nullable=True)
    tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    saved = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "model_used": self.model_used,
            "provider_used": self.provider_used,
            "tokens": self.tokens,
            "cost": round(self.cost, 5),
            "saved": round(self.saved, 5),
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class JudgeConsensusRecord(Base):
    __tablename__ = "judge_consensus"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), nullable=False, index=True)
    algorithm = Column(String(64), nullable=False)
    threshold = Column(Float, nullable=False)
    status = Column(String(32), nullable=False)
    winner_candidate_id = Column(String(64), nullable=True)
    agreement = Column(Float, nullable=False)
    result_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "request_id": self.request_id, "algorithm": self.algorithm,
                "threshold": self.threshold, "status": self.status,
                "winner_candidate_id": self.winner_candidate_id, "agreement": self.agreement,
                "result": json.loads(self.result_json) if isinstance(self.result_json, str) else self.result_json,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class JudgeExecutionRecord(Base):
    __tablename__ = "judge_executions"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), nullable=False, index=True)
    judge_type = Column(String(32), nullable=False)
    provider = Column(String(64), nullable=True)
    model_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False)
    provenance = Column(String(32), nullable=False)
    result_json = Column(Text, default="{}")
    error_code = Column(String(128), nullable=True)
    raw_output_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "request_id": self.request_id, "judge_type": self.judge_type,
                "provider": self.provider, "model_id": self.model_id, "status": self.status,
                "provenance": self.provenance,
                "result": json.loads(self.result_json) if isinstance(self.result_json, str) else self.result_json,
                "error_code": self.error_code, "raw_output_hash": self.raw_output_hash,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None}


class BenchmarkSuiteVersionRecord(Base):
    __tablename__ = "benchmark_suite_versions"

    id = Column(String(64), primary_key=True)
    suite_key = Column(String(128), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    name = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, default="")
    provenance = Column(String(32), nullable=False)
    source_uri = Column(String(1024), default="")
    content_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "suite_key": self.suite_key, "version": self.version, "name": self.name,
                "category": self.category, "description": self.description, "provenance": self.provenance,
                "source_uri": self.source_uri, "content_hash": self.content_hash,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class BenchmarkCaseRecord(Base):
    __tablename__ = "benchmark_cases"

    id = Column(String(64), primary_key=True)
    suite_version_id = Column(String(64), ForeignKey("benchmark_suite_versions.id"), nullable=False, index=True)
    case_key = Column(String(128), nullable=False)
    prompt = Column(Text, nullable=False)
    expected_behavior = Column(Text, nullable=False)
    evaluator_type = Column(String(32), nullable=False)
    evaluator_config = Column(Text, default="{}")
    category = Column(String(64), nullable=False)
    difficulty = Column(String(32), nullable=False)
    weight = Column(Float, nullable=False)
    provenance = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "suite_version_id": self.suite_version_id, "case_key": self.case_key,
                "prompt": self.prompt, "expected_behavior": self.expected_behavior,
                "evaluator_type": self.evaluator_type,
                "evaluator_config": json.loads(self.evaluator_config) if isinstance(self.evaluator_config, str) else self.evaluator_config,
                "category": self.category, "difficulty": self.difficulty, "weight": self.weight,
                "provenance": self.provenance, "created_at": self.created_at.isoformat() if self.created_at else None}


class BenchmarkRecord(Base):
    """Benchmark Dataset / Suite."""
    __tablename__ = "benchmarks"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, default="")
    difficulty = Column(String(32), default="medium")
    test_cases_count = Column(Integer, default=5)
    test_dataset = Column(Text, default="[]")
    last_run_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "difficulty": self.difficulty,
            "test_cases_count": self.test_cases_count,
            "test_dataset": json.loads(self.test_dataset) if isinstance(self.test_dataset, str) else self.test_dataset,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
        }


class BenchmarkScore(Base):
    """Individual model score on a benchmark."""
    __tablename__ = "benchmark_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(64), ForeignKey("models.id"))
    benchmark_id = Column(String(64), ForeignKey("benchmarks.id"))
    score = Column(Float, default=0.0)
    accuracy = Column(Float, default=0.0)
    speed_tps = Column(Float, default=0.0)
    cost_efficiency = Column(Float, default=0.0)
    passed_tests = Column(Integer, default=0)
    total_tests = Column(Integer, default=0)
    details = Column(Text, default="{}")
    run_date = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "benchmark_id": self.benchmark_id,
            "score": round(self.score, 1),
            "accuracy": round(self.accuracy, 1),
            "speed_tps": round(self.speed_tps, 1),
            "cost_efficiency": round(self.cost_efficiency, 1),
            "passed_tests": self.passed_tests,
            "total_tests": self.total_tests,
            "details": json.loads(self.details) if isinstance(self.details, str) else self.details,
            "run_date": self.run_date.isoformat() if self.run_date else None,
        }


class ArenaSessionRecord(Base):
    __tablename__ = "arena_sessions"

    id = Column(String(64), primary_key=True)
    run_a_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False)
    run_b_id = Column(String(64), ForeignKey("task_runs.id"), nullable=False)
    label_a_run_id = Column(String(64), nullable=False)
    label_b_run_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="awaiting_vote")
    winner_label = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    voted_at = Column(DateTime, nullable=True)


class ArenaVoteRecord(Base):
    """Blind AI Arena prompt comparison vote."""
    __tablename__ = "arena_votes"

    id = Column(String(64), primary_key=True)
    prompt = Column(Text, nullable=False)
    category = Column(String(64), default="general")
    model_a_id = Column(String(64), nullable=False)
    model_b_id = Column(String(64), nullable=False)
    winner = Column(String(16), nullable=False)
    response_a = Column(Text, default="")
    response_b = Column(Text, default="")
    latency_a_ms = Column(Integer, default=0)
    latency_b_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "category": self.category,
            "model_a_id": self.model_a_id,
            "model_b_id": self.model_b_id,
            "winner": self.winner,
            "latency_a_ms": self.latency_a_ms,
            "latency_b_ms": self.latency_b_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DelegateSkillRecord(Base):
    """Delegate Skill."""
    __tablename__ = "delegate_skills"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    category = Column(String(64), default="engineering")
    adapter_type = Column(String(32), default="prompt")
    script_path = Column(String(512), default="")
    prompt_template = Column(Text, default="")
    required_capabilities = Column(Text, default="[\"coding\"]")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "adapter_type": self.adapter_type,
            "script_path": self.script_path,
            "prompt_template": self.prompt_template,
            "required_capabilities": json.loads(self.required_capabilities) if isinstance(self.required_capabilities, str) else self.required_capabilities,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowTemplateVersionRecord(Base):
    __tablename__ = "workflow_template_versions"

    id = Column(String(64), primary_key=True)
    template_key = Column(String(128), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    name = Column(String(160), nullable=False)
    definition_json = Column(Text, nullable=False)
    prerequisites_json = Column(Text, default="[]")
    gate_ids_json = Column(Text, default="[]")
    provenance = Column(String(32), nullable=False)
    source_uri = Column(String(1024), nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True)
    executable = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template_key": self.template_key,
            "version": self.version,
            "name": self.name,
            "definition": json.loads(self.definition_json),
            "prerequisites": json.loads(self.prerequisites_json),
            "gate_ids": json.loads(self.gate_ids_json),
            "provenance": self.provenance,
            "source_uri": self.source_uri,
            "content_hash": self.content_hash,
            "executable": self.executable,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowRecord(Base):
    """Multi-Agent DAG Workflow."""
    __tablename__ = "workflows"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    template_type = Column(String(64), default="custom")
    nodes = Column(Text, default="[]")
    edges = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "template_type": self.template_type,
            "nodes": json.loads(self.nodes) if isinstance(self.nodes, str) else self.nodes,
            "edges": json.loads(self.edges) if isinstance(self.edges, str) else self.edges,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SubscriptionRecord(Base):
    """Tracked AI Subscriptions and quotas."""
    __tablename__ = "subscriptions"

    id = Column(String(64), primary_key=True)
    provider = Column(String(64), nullable=False)
    plan_name = Column(String(128), nullable=False)
    monthly_cost = Column(Float, default=0.0)
    usage_percentage = Column(Float, default=0.0)
    days_until_reset = Column(Integer, default=30)
    estimated_equivalent_api_value = Column(Float, default=0.0)
    status = Column(String(32), default="active")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "plan_name": self.plan_name,
            "monthly_cost": self.monthly_cost,
            "usage_percentage": self.usage_percentage,
            "days_until_reset": self.days_until_reset,
            "estimated_equivalent_api_value": self.estimated_equivalent_api_value,
            "status": self.status,
        }


class ModelFavoriteRecord(Base):
    __tablename__ = "model_favorites"

    id = Column(String(64), primary_key=True)
    model_id = Column(String(128), ForeignKey("models.id"), nullable=False, index=True)
    use_case = Column(String(64), nullable=False, index=True)
    provenance = Column(String(32), nullable=False, default="user_preference")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "model_id": self.model_id, "use_case": self.use_case,
                "provenance": self.provenance, "ranking_evidence": False,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class BudgetRecord(Base):
    __tablename__ = "budgets"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    amount = Column(String(64), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    period = Column(String(32), nullable=False, default="monthly")
    scope_type = Column(String(32), nullable=False, default="fleet")
    scope_id = Column(String(128), nullable=True)
    alert_threshold = Column(Float, nullable=False, default=80.0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "amount": self.amount, "currency": self.currency,
                "period": self.period, "scope_type": self.scope_type, "scope_id": self.scope_id,
                "alert_threshold": self.alert_threshold, "enabled": self.enabled,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class QuotaObservationRecord(Base):
    __tablename__ = "quota_observations"

    id = Column(String(64), primary_key=True)
    provider_instance_id = Column(String(64), nullable=False, index=True)
    scope = Column(String(64), nullable=False)
    unit = Column(String(32), default="unknown")
    limit_value = Column(Float, nullable=True)
    remaining_value = Column(Float, nullable=True)
    resets_at = Column(DateTime, nullable=True)
    source = Column(String(32), nullable=False)
    checked_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    evidence = Column(Text, default="{}")

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "provider_instance_id": self.provider_instance_id, "scope": self.scope,
                "unit": self.unit, "limit": self.limit_value, "remaining": self.remaining_value,
                "resets_at": self.resets_at.isoformat() if self.resets_at else None, "source": self.source,
                "checked_at": self.checked_at.isoformat(), "expires_at": self.expires_at.isoformat(),
                "evidence": json.loads(self.evidence) if isinstance(self.evidence, str) else self.evidence}


class LatencyObservationRecord(Base):
    __tablename__ = "latency_observations"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), nullable=False, index=True)
    attempt_id = Column(String(64), nullable=True, index=True)
    queue_ms = Column(Integer, nullable=True)
    launch_ms = Column(Integer, nullable=True)
    ttft_ms = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    tokens_per_second = Column(Float, nullable=True)
    source = Column(String(32), nullable=False)
    method = Column(String(128), nullable=True)
    metadata_json = Column(Text, default="{}")
    observed_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "attempt_id": self.attempt_id,
                "queue_ms": self.queue_ms, "launch_ms": self.launch_ms, "ttft_ms": self.ttft_ms,
                "duration_ms": self.duration_ms, "tokens_per_second": self.tokens_per_second,
                "source": self.source, "method": self.method,
                "metadata": json.loads(self.metadata_json) if isinstance(self.metadata_json, str) else self.metadata_json,
                "observed_at": self.observed_at.isoformat() if self.observed_at else None,
                "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None}


class UsageObservationRecord(Base):
    __tablename__ = "usage_observations"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), nullable=False, index=True)
    attempt_id = Column(String(64), nullable=True, index=True)
    model_id = Column(String(128), nullable=True, index=True)
    provider_instance_id = Column(String(64), nullable=True, index=True)
    requests = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cached_tokens = Column(Integer, nullable=True)
    reasoning_tokens = Column(Integer, nullable=True)
    source = Column(String(32), nullable=False)
    method = Column(String(128), nullable=True)
    metadata_json = Column(Text, default="{}")
    observed_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "run_id": self.run_id, "attempt_id": self.attempt_id,
            "model_id": self.model_id, "provider_instance_id": self.provider_instance_id,
            "requests": self.requests, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens, "source": self.source,
            "method": self.method,
            "metadata": json.loads(self.metadata_json) if isinstance(self.metadata_json, str) else self.metadata_json,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class AuditRecord(Base):
    __tablename__ = "audit_log"

    sequence = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(64), nullable=False, unique=True)
    action = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(128), nullable=False, index=True)
    outcome = Column(String(32), nullable=False)
    details = Column(Text, default="{}")
    correlation_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "audit_id": self.audit_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome,
            "details": json.loads(self.details) if isinstance(self.details, str) else self.details,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EventJournalRecord(Base):
    __tablename__ = "event_journal"

    sequence = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), nullable=False, unique=True)
    correlation_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(128), nullable=False)
    causation_id = Column(String(128), nullable=True)
    event_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id = Column(String(64), primary_key=True)
    action_type = Column(String(64), nullable=False)
    scope_type = Column(String(64), nullable=False)
    scope_id = Column(String(128), nullable=False)
    summary = Column(String(512), nullable=False)
    details = Column(Text, default="{}")
    status = Column(String(32), default="pending")
    requested_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    decision_reason = Column(String(1000), default="")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "summary": self.summary,
            "details": json.loads(self.details) if isinstance(self.details, str) else self.details,
            "status": self.status,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
            "decision_reason": self.decision_reason,
        }


class SystemSetting(Base):
    """System key-value settings."""
    __tablename__ = "system_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(String(256), default="")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "description": self.description,
        }
