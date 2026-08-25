import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(f"{self.version}:{self.name}".encode()).hexdigest()


AGENT_COLUMNS = {
    "input_method": "VARCHAR(32) DEFAULT 'argument'",
    "output_method": "VARCHAR(32) DEFAULT 'stdout'",
    "supports_pty": "BOOLEAN DEFAULT 0",
    "supports_interactive": "BOOLEAN DEFAULT 0",
    "tool_kind": "VARCHAR(32) DEFAULT 'agent'",
    "adapter_id": "VARCHAR(128) DEFAULT ''",
    "discovery_state": "VARCHAR(32) DEFAULT 'unavailable'",
    "discovery_source": "VARCHAR(32) DEFAULT 'manifest'",
    "discovery_evidence": "TEXT DEFAULT '{}'",
    "version_probe_args": "TEXT DEFAULT '[]'",
    "health_probe_args": "TEXT DEFAULT '[]'",
    "invocation_args": "TEXT DEFAULT '[]'",
    "environment_refs": "TEXT DEFAULT '[]'",
    "secret_refs": "TEXT DEFAULT '[]'",
    "working_directory": "VARCHAR(32) DEFAULT 'workspace'",
    "probe_timeout_seconds": "FLOAT DEFAULT 3.0",
    "last_checked_at": "DATETIME",
    "user_enabled": "BOOLEAN DEFAULT 1",
    "lifecycle_status": "VARCHAR(32) DEFAULT 'active'",
    "revision": "INTEGER DEFAULT 1",
    "updated_at": "DATETIME",
    "auth_state": "VARCHAR(32) DEFAULT 'unknown'",
    "auth_method": "VARCHAR(64) DEFAULT 'unknown'",
    "auth_evidence": "TEXT DEFAULT '{}'",
    "auth_checked_at": "DATETIME",
    "auth_setup_action": "TEXT DEFAULT '{}'",
    "auth_probe_args": "TEXT DEFAULT '[]'",
    "auth_probe_parser": "TEXT DEFAULT '{}'",
}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _add_missing(connection: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
    existing = _columns(connection, table)
    for name, definition in definitions.items():
        if name not in existing:
            connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def _migration_001(connection: sqlite3.Connection) -> None:
    if "task_runs" in _tables(connection):
        _add_missing(connection, "task_runs", {"workspace_id": "VARCHAR(64)"})
    if "agents" in _tables(connection):
        _add_missing(connection, "agents", {key: AGENT_COLUMNS[key] for key in ["input_method", "output_method", "supports_pty", "supports_interactive"]})


def _migration_002(connection: sqlite3.Connection) -> None:
    if "agents" not in _tables(connection):
        return
    _add_missing(connection, "agents", AGENT_COLUMNS)
    connection.execute("UPDATE agents SET supports_interactive = 0 WHERE supports_pty = 0")
    connection.execute("UPDATE agents SET revision = 1 WHERE revision IS NULL OR revision < 1")
    connection.execute("UPDATE agents SET discovery_state = 'unavailable', status = 'unavailable' WHERE is_installed = 0 AND discovery_source != 'manual'")


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _migration_003(connection: sqlite3.Connection) -> None:
    if "models" not in _tables(connection):
        return
    _add_missing(connection, "models", {
        "registry_state": "VARCHAR(32) DEFAULT 'catalog'",
        "lifecycle_status": "VARCHAR(32) DEFAULT 'active'",
        "availability_state": "VARCHAR(32) DEFAULT 'unknown'",
        "availability_evidence": "TEXT DEFAULT '{}'",
        "availability_checked_at": "DATETIME",
        "source_type": "VARCHAR(32) DEFAULT 'catalog'",
        "source_uri": "VARCHAR(1024) DEFAULT ''",
        "source_checked_at": "DATETIME",
        "metadata_provenance": "VARCHAR(32) DEFAULT 'unverified'",
        "pricing_provenance": "VARCHAR(32) DEFAULT 'unknown'",
        "capability_provenance": "VARCHAR(32) DEFAULT 'unknown'",
        "pricing_currency": "VARCHAR(8) DEFAULT 'USD'",
        "pricing_effective_at": "DATETIME",
        "revision": "INTEGER DEFAULT 1",
    })
    connection.execute("UPDATE models SET registry_state='catalog', availability_state='unknown', metadata_provenance='unverified', pricing_provenance='unknown', capability_provenance='unknown' WHERE source_type='catalog' OR source_type IS NULL")


def _migration_004(connection: sqlite3.Connection) -> None:
    if "models" not in _tables(connection):
        return
    existing = _columns(connection, "models")
    assignments = []
    for field in ["quality_score", "coding_score", "reasoning_score", "arabic_score", "vision_score", "speed_score", "reliability_score", "tokens_per_sec"]:
        if field in existing:
            assignments.append(f"{field}=NULL")
    for field in ["best_for", "not_ideal_for"]:
        if field in existing:
            assignments.append(f"{field}='[]'")
    if "is_free" in existing:
        assignments.append("is_free=0")
    if assignments:
        connection.execute(f"UPDATE models SET {', '.join(assignments)} WHERE capability_provenance='unknown'")


def _migration_005(connection: sqlite3.Connection) -> None:
    if "models" in _tables(connection):
        _add_missing(connection, "models", {"availability_expires_at": "DATETIME"})


def _migration_006(connection: sqlite3.Connection) -> None:
    if "models" not in _tables(connection):
        return
    existing = _columns(connection, "models")
    fields = [field for field in ["input_cost_per_m", "output_cost_per_m", "cache_cost_per_m", "reasoning_cost_per_m"] if field in existing]
    if fields:
        connection.execute(f"UPDATE models SET {', '.join(f'{field}=NULL' for field in fields)} WHERE pricing_provenance='unknown'")


def _migration_007(connection: sqlite3.Connection) -> None:
    if "task_runs" not in _tables(connection):
        return
    _add_missing(connection, "task_runs", {
        "token_provenance": "VARCHAR(32) DEFAULT 'unknown'",
        "cost_provenance": "VARCHAR(32) DEFAULT 'unknown'",
        "quality_provenance": "VARCHAR(32) DEFAULT 'unknown'",
        "latency_provenance": "VARCHAR(32) DEFAULT 'measured'",
        "measurement_metadata": "TEXT DEFAULT '{}'",
    })
    connection.execute("UPDATE task_runs SET token_provenance='estimated', cost_provenance='unknown', quality_provenance='unknown', latency_provenance='measured' WHERE token_provenance='unknown'")


def _migration_008(connection: sqlite3.Connection) -> None:
    if "plugins" not in _tables(connection):
        return
    _add_missing(connection, "plugins", {
        "granted_permissions": "TEXT DEFAULT '[]'",
        "permission_profile": "VARCHAR(32) DEFAULT 'safe'",
        "package_hash": "VARCHAR(64) DEFAULT ''",
        "entrypoint": "VARCHAR(1024) DEFAULT ''",
        "load_state": "VARCHAR(32) DEFAULT 'registered'",
    })


def _migration_009(connection: sqlite3.Connection) -> None:
    if "task_runs" not in _tables(connection):
        return
    _add_missing(connection, "task_runs", {
        "project_id": "VARCHAR(64)", "workflow_id": "VARCHAR(64)", "current_attempt_id": "VARCHAR(64)",
        "status_reason": "VARCHAR(128)", "cancellation_requested_at": "DATETIME",
        "started_at": "DATETIME", "completed_at": "DATETIME", "revision": "INTEGER DEFAULT 1",
    })


def _migration_010(connection: sqlite3.Connection) -> None:
    if "task_runs" not in _tables(connection):
        return
    _add_missing(connection, "task_runs", {"financials_json": "TEXT DEFAULT '{}'"})
    connection.execute("UPDATE task_runs SET financials_json='{}' WHERE financials_json IS NULL")


def _migration_011(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id VARCHAR(64) PRIMARY KEY, name VARCHAR(128) NOT NULL, amount VARCHAR(64) NOT NULL,
        currency VARCHAR(8) NOT NULL DEFAULT 'USD', period VARCHAR(32) NOT NULL DEFAULT 'monthly',
        scope_type VARCHAR(32) NOT NULL DEFAULT 'fleet', scope_id VARCHAR(128),
        alert_threshold FLOAT NOT NULL DEFAULT 80.0, enabled BOOLEAN NOT NULL DEFAULT 1,
        created_at DATETIME, updated_at DATETIME
    )""")


def _migration_012(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS model_favorites (
        id VARCHAR(64) PRIMARY KEY, model_id VARCHAR(128) NOT NULL, use_case VARCHAR(64) NOT NULL,
        provenance VARCHAR(32) NOT NULL DEFAULT 'user_preference', created_at DATETIME,
        FOREIGN KEY(model_id) REFERENCES models(id), UNIQUE(model_id, use_case)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_model_favorites_model_id ON model_favorites(model_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_model_favorites_use_case ON model_favorites(use_case)")


def _migration_039(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS deliverables (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
        name VARCHAR(256) NOT NULL, component VARCHAR(128), version VARCHAR(64) NOT NULL,
        relative_path VARCHAR(1024) NOT NULL, checksum VARCHAR(64) NOT NULL, readiness VARCHAR(32) NOT NULL,
        requirement_ids_json TEXT NOT NULL DEFAULT '[]', asset_ids_json TEXT NOT NULL DEFAULT '[]',
        run_ids_json TEXT NOT NULL DEFAULT '[]', gate_ids_json TEXT NOT NULL DEFAULT '[]', created_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
        UNIQUE(project_id, name, version)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_deliverables_project_id ON deliverables(project_id)")


def _migration_038(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS orchestration_checkpoints (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, state VARCHAR(32) NOT NULL,
        cursor_json TEXT NOT NULL DEFAULT '{}', ready_queue_json TEXT NOT NULL DEFAULT '[]',
        active_task_ids_json TEXT NOT NULL DEFAULT '[]', lock_keys_json TEXT NOT NULL DEFAULT '[]',
        revision INTEGER NOT NULL DEFAULT 1, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_orchestration_checkpoints_project_id ON orchestration_checkpoints(project_id)")


def _migration_037(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS quality_waivers (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, finding_id VARCHAR(128) NOT NULL,
        scope_type VARCHAR(32) NOT NULL, scope_id VARCHAR(128) NOT NULL, reason TEXT NOT NULL,
        risk TEXT NOT NULL, owner VARCHAR(128) NOT NULL, expires_at DATETIME NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active', created_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_quality_waivers_project_id ON quality_waivers(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_quality_waivers_finding_id ON quality_waivers(finding_id)")


def _migration_036(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS acceptance_criteria (
        id VARCHAR(64) PRIMARY KEY, task_id VARCHAR(64) NOT NULL, criterion_type VARCHAR(32) NOT NULL,
        description TEXT NOT NULL, evaluator VARCHAR(64) NOT NULL, severity VARCHAR(16) NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '[]', status VARCHAR(32) NOT NULL DEFAULT 'pending',
        waiver_json TEXT, created_at DATETIME, FOREIGN KEY(task_id) REFERENCES orchestration_tasks(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_acceptance_criteria_task_id ON acceptance_criteria(task_id)")


def _migration_035(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS orchestration_tasks (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, task_type VARCHAR(64) NOT NULL,
        title VARCHAR(256) NOT NULL, description TEXT DEFAULT '', requirement_ids_json TEXT NOT NULL DEFAULT '[]',
        dependency_ids_json TEXT NOT NULL DEFAULT '[]', acceptance_json TEXT NOT NULL DEFAULT '[]',
        context_refs_json TEXT NOT NULL DEFAULT '[]', executor_needs_json TEXT NOT NULL DEFAULT '{}',
        state VARCHAR(32) NOT NULL DEFAULT 'planned', current_run_id VARCHAR(64), revision INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME, updated_at DATETIME, FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(current_run_id) REFERENCES task_runs(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_orchestration_tasks_project_id ON orchestration_tasks(project_id)")


def _migration_034(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS asset_collections (
        id VARCHAR(64) PRIMARY KEY, name VARCHAR(256) NOT NULL, owner VARCHAR(128) NOT NULL,
        description TEXT DEFAULT '', created_at DATETIME
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS asset_collection_members (
        id VARCHAR(64) PRIMARY KEY, collection_id VARCHAR(64) NOT NULL, asset_id VARCHAR(64) NOT NULL,
        added_at DATETIME, FOREIGN KEY(collection_id) REFERENCES asset_collections(id),
        FOREIGN KEY(asset_id) REFERENCES assets(id), UNIQUE(collection_id, asset_id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_collection_members_collection_id ON asset_collection_members(collection_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_collection_members_asset_id ON asset_collection_members(asset_id)")
    connection.execute("""CREATE TABLE IF NOT EXISTS asset_collection_project_links (
        id VARCHAR(64) PRIMARY KEY, collection_id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT NULL,
        linked_at DATETIME, FOREIGN KEY(collection_id) REFERENCES asset_collections(id),
        FOREIGN KEY(project_id) REFERENCES projects(id), UNIQUE(collection_id, project_id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_collection_project_links_collection_id ON asset_collection_project_links(collection_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_collection_project_links_project_id ON asset_collection_project_links(project_id)")


def _migration_033(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS asset_transform_jobs (id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), original_asset_id VARCHAR(64) NOT NULL, derivative_asset_id VARCHAR(64), tool VARCHAR(128) NOT NULL, tool_version VARCHAR(64) NOT NULL, parameters_json TEXT NOT NULL, status VARCHAR(32) NOT NULL, input_hash VARCHAR(64) NOT NULL, output_hash VARCHAR(64), provenance VARCHAR(32) NOT NULL, created_at DATETIME, completed_at DATETIME, FOREIGN KEY(run_id) REFERENCES task_runs(id), FOREIGN KEY(original_asset_id) REFERENCES assets(id), FOREIGN KEY(derivative_asset_id) REFERENCES assets(id))")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_transform_jobs_original_asset_id ON asset_transform_jobs(original_asset_id)")


def _migration_032(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS asset_licenses (id VARCHAR(128) PRIMARY KEY, name VARCHAR(256) NOT NULL, source_uri VARCHAR(2048), restrictions_json TEXT NOT NULL DEFAULT '[]', confidence VARCHAR(16) NOT NULL, approval_status VARCHAR(32) NOT NULL DEFAULT 'pending', approved_by VARCHAR(128), created_at DATETIME)")


def _migration_031(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS asset_usage (id VARCHAR(64) PRIMARY KEY, asset_id VARCHAR(64) NOT NULL, target_type VARCHAR(32) NOT NULL, target_id VARCHAR(128) NOT NULL, usage_role VARCHAR(64) NOT NULL, required BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME, FOREIGN KEY(asset_id) REFERENCES assets(id), UNIQUE(asset_id,target_type,target_id,usage_role))")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_usage_asset_id ON asset_usage(asset_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_asset_usage_target_id ON asset_usage(target_id)")


def _migration_030(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS research_claims (id VARCHAR(64) PRIMARY KEY, query_id VARCHAR(64) NOT NULL, project_id VARCHAR(64) NOT NULL, requirement_id VARCHAR(64), statement TEXT NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'unsupported', created_at DATETIME, FOREIGN KEY(query_id) REFERENCES research_queries(id), FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(requirement_id) REFERENCES project_requirements(id))")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_research_claims_query_id ON research_claims(query_id)")
    connection.execute("CREATE TABLE IF NOT EXISTS research_citations (id VARCHAR(64) PRIMARY KEY, claim_id VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL, excerpt TEXT NOT NULL, excerpt_hash VARCHAR(64) NOT NULL, locator VARCHAR(256), created_at DATETIME, FOREIGN KEY(claim_id) REFERENCES research_claims(id), FOREIGN KEY(source_id) REFERENCES research_sources(id), UNIQUE(claim_id,source_id,excerpt_hash))")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_research_citations_claim_id ON research_citations(claim_id)")


def _migration_029(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS research_sources (
        id VARCHAR(64) PRIMARY KEY, query_id VARCHAR(64) NOT NULL, url VARCHAR(2048) NOT NULL,
        title VARCHAR(512) NOT NULL, source_type VARCHAR(64) NOT NULL, author VARCHAR(256),
        retrieved_at DATETIME NOT NULL, freshness_at DATETIME, content_hash VARCHAR(64) NOT NULL,
        version INTEGER NOT NULL, license_id VARCHAR(128), confidence FLOAT, metadata_json TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY(query_id) REFERENCES research_queries(id), UNIQUE(query_id,url,version)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_research_sources_query_id ON research_sources(query_id)")


def _migration_028(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS assets (
        id VARCHAR(64) PRIMARY KEY, scope_type VARCHAR(32) NOT NULL, project_id VARCHAR(64),
        workspace_id VARCHAR(64) NOT NULL, relative_path VARCHAR(1024) NOT NULL, asset_type VARCHAR(32),
        mime_type VARCHAR(128), sha256 VARCHAR(64) NOT NULL, source_type VARCHAR(32) NOT NULL,
        source_id VARCHAR(128), provenance VARCHAR(32) NOT NULL, license_id VARCHAR(128),
        width INTEGER, height INTEGER, duration_ms INTEGER, size_bytes INTEGER NOT NULL,
        state VARCHAR(32) NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
        UNIQUE(workspace_id, relative_path, sha256)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_assets_project_id ON assets(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_assets_sha256 ON assets(sha256)")


def _migration_027(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS research_queries (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, question TEXT NOT NULL,
        query_kind VARCHAR(32) NOT NULL, freshness_after DATETIME, source_policy_json TEXT NOT NULL,
        claim_ids_json TEXT NOT NULL DEFAULT '[]', project_usage_json TEXT NOT NULL DEFAULT '[]',
        status VARCHAR(32) NOT NULL DEFAULT 'draft', created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_research_queries_project_id ON research_queries(project_id)")


def _migration_026(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS context_packs (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64), run_id VARCHAR(64), manifest_json TEXT NOT NULL,
        token_count INTEGER NOT NULL, token_provenance VARCHAR(32) NOT NULL, token_method VARCHAR(128),
        redactions_json TEXT NOT NULL DEFAULT '[]', generated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(run_id) REFERENCES task_runs(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_context_packs_project_id ON context_packs(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_context_packs_run_id ON context_packs(run_id)")


def _migration_025(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS project_learning_consent (project_id VARCHAR(64) PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT 0, granted_by VARCHAR(128), updated_at DATETIME, FOREIGN KEY(project_id) REFERENCES projects(id))")
    connection.execute("""CREATE TABLE IF NOT EXISTS project_outcomes (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, run_id VARCHAR(64) NOT NULL UNIQUE,
        task_category VARCHAR(64) NOT NULL, route_id VARCHAR(256) NOT NULL, outcome VARCHAR(32) NOT NULL,
        preferred BOOLEAN NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}', created_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(run_id) REFERENCES task_runs(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_outcomes_project_id ON project_outcomes(project_id)")


def _migration_024(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS project_needs (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, requirement_id VARCHAR(64),
        need_type VARCHAR(32) NOT NULL, title VARCHAR(256) NOT NULL, description TEXT NOT NULL,
        source_type VARCHAR(32) NOT NULL, source_id VARCHAR(128), impact VARCHAR(32) NOT NULL,
        blocked_nodes_json TEXT NOT NULL DEFAULT '[]', state VARCHAR(32) NOT NULL DEFAULT 'open',
        resolution_json TEXT, dedupe_key VARCHAR(128) NOT NULL, created_at DATETIME, resolved_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(requirement_id) REFERENCES project_requirements(id),
        UNIQUE(project_id, dedupe_key)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_needs_project_id ON project_needs(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_needs_requirement_id ON project_needs(requirement_id)")


def _migration_023(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS blueprint_proposals (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, template_id VARCHAR(128) NOT NULL,
        template_version VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'proposed',
        content_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, approved_by VARCHAR(128),
        approved_at DATETIME, created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_blueprint_proposals_project_id ON blueprint_proposals(project_id)")
    connection.execute("""CREATE TABLE IF NOT EXISTS blueprint_proposal_revisions (
        id VARCHAR(64) PRIMARY KEY, proposal_id VARCHAR(64) NOT NULL, revision INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, created_at DATETIME,
        FOREIGN KEY(proposal_id) REFERENCES blueprint_proposals(id), UNIQUE(proposal_id, revision)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_blueprint_proposal_revisions_proposal_id ON blueprint_proposal_revisions(proposal_id)")


def _migration_022(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS project_requirement_edges (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL,
        target_id VARCHAR(64) NOT NULL, edge_type VARCHAR(32) NOT NULL, rationale TEXT NOT NULL,
        created_at DATETIME, FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(source_id) REFERENCES project_requirements(id), FOREIGN KEY(target_id) REFERENCES project_requirements(id),
        UNIQUE(source_id, target_id, edge_type)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirement_edges_project_id ON project_requirement_edges(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirement_edges_source_id ON project_requirement_edges(source_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirement_edges_target_id ON project_requirement_edges(target_id)")


def _migration_021(connection: sqlite3.Connection) -> None:
    _add_missing(connection, "project_requirements", {"waiver_rationale": "TEXT", "waived_by": "VARCHAR(128)"})
    connection.execute("""CREATE TABLE IF NOT EXISTS project_requirement_revisions (
        id VARCHAR(64) PRIMARY KEY, requirement_id VARCHAR(64) NOT NULL, revision INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, created_at DATETIME,
        FOREIGN KEY(requirement_id) REFERENCES project_requirements(id), UNIQUE(requirement_id, revision)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirement_revisions_requirement_id ON project_requirement_revisions(requirement_id)")


def _migration_020(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS project_requirements (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, parent_id VARCHAR(64),
        title VARCHAR(256) NOT NULL, description TEXT DEFAULT '', requirement_type VARCHAR(32) NOT NULL,
        source_type VARCHAR(32) NOT NULL, source_id VARCHAR(128), truth_state VARCHAR(32) NOT NULL,
        priority VARCHAR(16) NOT NULL, status VARCHAR(32) NOT NULL, acceptance_json TEXT NOT NULL DEFAULT '[]',
        evidence_json TEXT NOT NULL DEFAULT '[]', owner VARCHAR(128), revision INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(parent_id) REFERENCES project_requirements(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirements_project_id ON project_requirements(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_requirements_parent_id ON project_requirements(parent_id)")


def _migration_019(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS project_decisions (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, scope_type VARCHAR(32) NOT NULL,
        scope_id VARCHAR(128), statement TEXT NOT NULL, rationale TEXT NOT NULL, impact TEXT NOT NULL,
        rule_json TEXT NOT NULL, source_type VARCHAR(32) NOT NULL, source_id VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'proposed', supersedes_id VARCHAR(64), approved_by VARCHAR(128),
        approved_at DATETIME, revision INTEGER NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(supersedes_id) REFERENCES project_decisions(id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_decisions_project_id ON project_decisions(project_id)")
    connection.execute("""CREATE TABLE IF NOT EXISTS project_decision_revisions (
        id VARCHAR(64) PRIMARY KEY, decision_id VARCHAR(64) NOT NULL, revision INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, created_at DATETIME,
        FOREIGN KEY(decision_id) REFERENCES project_decisions(id), UNIQUE(decision_id, revision)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_decision_revisions_decision_id ON project_decision_revisions(decision_id)")


def _migration_018(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS project_brain_facts (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, section VARCHAR(64) NOT NULL,
        fact_key VARCHAR(128) NOT NULL, value_json TEXT NOT NULL, truth_state VARCHAR(32) NOT NULL,
        provenance VARCHAR(32) NOT NULL, source_type VARCHAR(32) NOT NULL, source_id VARCHAR(128),
        confidence FLOAT, revision INTEGER NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), UNIQUE(project_id, section, fact_key)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_brain_facts_project_id ON project_brain_facts(project_id)")
    connection.execute("""CREATE TABLE IF NOT EXISTS project_brain_fact_revisions (
        id VARCHAR(64) PRIMARY KEY, fact_id VARCHAR(64) NOT NULL, revision INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, created_at DATETIME,
        FOREIGN KEY(fact_id) REFERENCES project_brain_facts(id), UNIQUE(fact_id, revision)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_brain_fact_revisions_fact_id ON project_brain_fact_revisions(fact_id)")


def _migration_017(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS projects (
        id VARCHAR(64) PRIMARY KEY, name VARCHAR(128) NOT NULL, slug VARCHAR(128) NOT NULL UNIQUE,
        purpose TEXT DEFAULT '', project_type VARCHAR(64) NOT NULL, owner VARCHAR(128) NOT NULL,
        lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active', revision INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME, updated_at DATETIME
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_projects_slug ON projects(slug)")
    connection.execute("""CREATE TABLE IF NOT EXISTS project_workspace_links (
        id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'primary', created_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
        UNIQUE(project_id, workspace_id)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_workspace_links_project_id ON project_workspace_links(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_project_workspace_links_workspace_id ON project_workspace_links(workspace_id)")


def _migration_016(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS arena_sessions (
        id VARCHAR(64) PRIMARY KEY, run_a_id VARCHAR(64) NOT NULL, run_b_id VARCHAR(64) NOT NULL,
        label_a_run_id VARCHAR(64) NOT NULL, label_b_run_id VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'awaiting_vote', winner_label VARCHAR(16),
        created_at DATETIME, voted_at DATETIME,
        FOREIGN KEY(run_a_id) REFERENCES task_runs(id), FOREIGN KEY(run_b_id) REFERENCES task_runs(id)
    )""")


def _migration_015(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS judge_consensus (
        id VARCHAR(64) PRIMARY KEY, request_id VARCHAR(64) NOT NULL, algorithm VARCHAR(64) NOT NULL,
        threshold FLOAT NOT NULL, status VARCHAR(32) NOT NULL, winner_candidate_id VARCHAR(64),
        agreement FLOAT NOT NULL, result_json TEXT DEFAULT '{}', created_at DATETIME
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_judge_consensus_request_id ON judge_consensus(request_id)")


def _migration_014(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS judge_executions (
        id VARCHAR(64) PRIMARY KEY, request_id VARCHAR(64) NOT NULL, judge_type VARCHAR(32) NOT NULL,
        provider VARCHAR(64), model_id VARCHAR(128), status VARCHAR(32) NOT NULL,
        provenance VARCHAR(32) NOT NULL, result_json TEXT DEFAULT '{}', error_code VARCHAR(128),
        raw_output_hash VARCHAR(64), created_at DATETIME, completed_at DATETIME
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_judge_executions_request_id ON judge_executions(request_id)")


def _migration_013(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS benchmark_suite_versions (
        id VARCHAR(64) PRIMARY KEY, suite_key VARCHAR(128) NOT NULL, version INTEGER NOT NULL,
        name VARCHAR(128) NOT NULL, category VARCHAR(64) NOT NULL, description TEXT DEFAULT '',
        provenance VARCHAR(32) NOT NULL, source_uri VARCHAR(1024) DEFAULT '', content_hash VARCHAR(64) NOT NULL UNIQUE,
        created_at DATETIME, UNIQUE(suite_key, version)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_benchmark_suite_versions_suite_key ON benchmark_suite_versions(suite_key)")
    connection.execute("""CREATE TABLE IF NOT EXISTS benchmark_cases (
        id VARCHAR(64) PRIMARY KEY, suite_version_id VARCHAR(64) NOT NULL, case_key VARCHAR(128) NOT NULL,
        prompt TEXT NOT NULL, expected_behavior TEXT NOT NULL, evaluator_type VARCHAR(32) NOT NULL,
        evaluator_config TEXT DEFAULT '{}', category VARCHAR(64) NOT NULL, difficulty VARCHAR(32) NOT NULL,
        weight FLOAT NOT NULL, provenance VARCHAR(32) NOT NULL, created_at DATETIME,
        FOREIGN KEY(suite_version_id) REFERENCES benchmark_suite_versions(id), UNIQUE(suite_version_id, case_key)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_benchmark_cases_suite_version_id ON benchmark_cases(suite_version_id)")


def _migration_040(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS plugin_catalog_sources (
        id VARCHAR(128) PRIMARY KEY, index_url VARCHAR(1024) NOT NULL UNIQUE, public_key TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT 0, last_state VARCHAR(32) NOT NULL DEFAULT 'never_refreshed',
        last_error TEXT DEFAULT '', catalog_json TEXT DEFAULT '{}', verified_at DATETIME, expires_at DATETIME,
        created_at DATETIME, updated_at DATETIME
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS plugins (
        id VARCHAR(128) PRIMARY KEY, name VARCHAR(160) NOT NULL, path VARCHAR(1024) NOT NULL UNIQUE,
        version VARCHAR(64) DEFAULT '0.1.0', protocol_version VARCHAR(32) DEFAULT '1.x',
        plugin_type VARCHAR(64) DEFAULT 'cli', status VARCHAR(32) DEFAULT 'registered', manifest TEXT DEFAULT '{}',
        permissions TEXT DEFAULT '[]', granted_permissions TEXT DEFAULT '[]', permission_profile VARCHAR(32) DEFAULT 'safe',
        package_hash VARCHAR(64) DEFAULT '', entrypoint VARCHAR(1024) DEFAULT '', load_state VARCHAR(32) DEFAULT 'registered',
        created_at DATETIME
    )""")
    existing = {row[1] for row in connection.execute("PRAGMA table_info(plugins)")}
    additions = {
        "source_type": "VARCHAR(32) DEFAULT 'local'",
        "source_id": "VARCHAR(128)",
        "source_package_url": "VARCHAR(1024)",
        "previous_path": "VARCHAR(1024)",
        "previous_hash": "VARCHAR(64)",
        "installed_at": "DATETIME",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE plugins ADD COLUMN {name} {definition}")


def _migration_041(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS workflow_template_versions (
        id VARCHAR(64) PRIMARY KEY, template_key VARCHAR(128) NOT NULL, version VARCHAR(64) NOT NULL,
        name VARCHAR(160) NOT NULL, definition_json TEXT NOT NULL, prerequisites_json TEXT DEFAULT '[]',
        gate_ids_json TEXT DEFAULT '[]', provenance VARCHAR(32) NOT NULL, source_uri VARCHAR(1024) NOT NULL,
        content_hash VARCHAR(64) NOT NULL UNIQUE, executable BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME,
        UNIQUE(template_key, version)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_workflow_template_versions_template_key ON workflow_template_versions(template_key)")


MIGRATIONS = [
    Migration(1, "legacy_execution_columns", _migration_001),
    Migration(2, "agent_registry_lifecycle", _migration_002),
    Migration(3, "model_truth_foundation", _migration_003),
    Migration(4, "remove_unverified_model_scores", _migration_004),
    Migration(5, "model_availability_expiry", _migration_005),
    Migration(6, "remove_unverified_model_prices", _migration_006),
    Migration(7, "run_measurement_provenance", _migration_007),
    Migration(8, "plugin_trust_boundary", _migration_008),
    Migration(9, "canonical_run_fields", _migration_009),
    Migration(10, "run_financial_evidence", _migration_010),
    Migration(11, "budget_records", _migration_011),
    Migration(12, "model_favorites", _migration_012),
    Migration(13, "versioned_benchmark_schema", _migration_013),
    Migration(14, "judge_executions", _migration_014),
    Migration(15, "judge_consensus", _migration_015),
    Migration(16, "blind_arena_sessions", _migration_016),
    Migration(17, "project_identity", _migration_017),
    Migration(18, "project_brain_facts", _migration_018),
    Migration(19, "project_decisions", _migration_019),
    Migration(20, "project_requirements", _migration_020),
    Migration(21, "requirement_lifecycle", _migration_021),
    Migration(22, "requirement_edges", _migration_022),
    Migration(23, "blueprint_proposals", _migration_023),
    Migration(24, "project_needs", _migration_024),
    Migration(25, "project_learning", _migration_025),
    Migration(26, "context_packs", _migration_026),
    Migration(27, "research_queries", _migration_027),
    Migration(28, "assets", _migration_028),
    Migration(29, "research_sources", _migration_029),
    Migration(30, "research_claims", _migration_030),
    Migration(31, "asset_usage", _migration_031),
    Migration(32, "asset_licenses", _migration_032),
    Migration(33, "asset_transform_jobs", _migration_033),
    Migration(34, "asset_collections", _migration_034),
    Migration(35, "orchestration_tasks", _migration_035),
    Migration(36, "acceptance_criteria", _migration_036),
    Migration(37, "quality_waivers", _migration_037),
    Migration(38, "orchestration_checkpoints", _migration_038),
    Migration(39, "deliverables", _migration_039),
    Migration(40, "plugin_marketplace", _migration_040),
    Migration(41, "workflow_template_marketplace", _migration_041),
]


class MigrationRunner:
    def __init__(self, database_path: Path, backup_limit: int = 3):
        self.database_path = database_path
        self.backup_dir = database_path.parent / "backups"
        self.backup_limit = backup_limit

    def migrate(self) -> List[int]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        try:
            self._ensure_table(connection)
            applied = {row[0]: row[1] for row in connection.execute("SELECT version, checksum FROM schema_migrations")}
            pending = [migration for migration in MIGRATIONS if migration.version not in applied]
            for migration in MIGRATIONS:
                if migration.version in applied and applied[migration.version] != migration.checksum:
                    raise RuntimeError(f"Migration checksum mismatch for version {migration.version}.")
            if not pending:
                return []
            backup = self._backup(connection)
            completed = []
            try:
                for migration in pending:
                    connection.execute("BEGIN IMMEDIATE")
                    migration.apply(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                        (migration.version, migration.name, migration.checksum, datetime.now(timezone.utc).isoformat()),
                    )
                    connection.commit()
                    completed.append(migration.version)
                self._write_recovery_metadata(backup, completed, "completed")
                self._prune_backups()
                return completed
            except Exception:
                connection.rollback()
                connection.close()
                if backup:
                    shutil.copy2(backup, self.database_path)
                    self._write_recovery_metadata(backup, completed, "restored_after_failure")
                raise
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _ensure_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.commit()

    def _backup(self, connection: sqlite3.Connection) -> Optional[Path]:
        if not self.database_path.exists() or self.database_path.stat().st_size == 0:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.backup_dir / f"{self.database_path.stem}-{stamp}.db"
        backup_connection = sqlite3.connect(destination)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()
        return destination

    def _write_recovery_metadata(self, backup: Optional[Path], versions: List[int], state: str) -> None:
        metadata = {
            "database": str(self.database_path),
            "backup": str(backup) if backup else None,
            "versions": versions,
            "state": state,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        (self.database_path.parent / "migration-recovery.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _prune_backups(self) -> None:
        if not self.backup_dir.exists():
            return
        backups = sorted(self.backup_dir.glob(f"{self.database_path.stem}-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in backups[self.backup_limit:]:
            path.unlink(missing_ok=True)
