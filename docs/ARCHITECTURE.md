# AI Fleet OS Architecture

## System boundary

AI Fleet OS is a local-first FastAPI and React application. SQLite stores registry, execution, project, evidence, and audit records. The browser communicates with local REST and WebSocket APIs. External CLI and provider execution always crosses an adapter and permission boundary.

## Domain map

Canonical domain identities are defined in `core/ai_fleet/domain.py`:

- Project: persistent outcome, truth, plan, and delivery scope.
- Workspace: approved filesystem boundary; never the Project identity.
- Agent: executable tool with capabilities and permissions.
- Runtime: execution environment or local model host.
- Model: model identity and evidence; not an executable Agent.
- Provider: configured service instance.
- Skill: reusable capability requirement and recipe.
- Requirement, Task, Run, Asset, and Deliverable: evidence-linked project records.

## Execution

- `core/ai_fleet/engine/process_manager.py`: argv-based process lifecycle, streaming, timeout, cancellation, receipts, and PTY integration.
- `core/ai_fleet/services/runs.py`: canonical run and attempt transitions and restart recovery.
- `core/ai_fleet/services/run_output.py` and `run_artifacts.py`: bounded redacted output and workspace-contained artifact evidence.
- `core/ai_fleet/services/provider_runtime.py`: provider adapter registry and cancellation.
- `core/ai_fleet/engine/execution_readiness.py`: verifies executable Agent/workspace or provider/model routes before launch.

## Security

`docs/SECURITY_THREAT_MODEL.md` is authoritative. Primary controls include local Origin/Host policy, request limits, secret redaction and vault references, argv execution, workspace `PathPolicy`, permission profiles, scoped approvals, plugin subprocess isolation, URL SSRF policy, bounded downloads, and export redaction.

## Plugins and providers

- `core/ai_fleet/plugin_protocol.py`: versioned brand-neutral plugin manifest.
- `core/ai_fleet/services/plugin_runtime.py`: out-of-process RPC lifecycle and reload safety.
- `core/ai_fleet/providers.py`: brand-neutral provider capability contract.
- `core/ai_fleet/services/provider_registry.py`: configured instances, health, secret references, and model observations.

## Projects and Project Brain

Projects are distinct from Workspaces. Project services persist lifecycle, workspace links, structured Brain facts and immutable revisions, decisions, hierarchical requirements and dependency edges, missing needs, blueprint proposals, orchestration tasks, and quality evidence. Project UI lives in `apps/web/src/components/Projects.tsx`.

## Context

Typed source references are defined in `core/ai_fleet/context.py`. Relevance selection is explicit-graph based. File excerpts are workspace-contained, bounded, encoding-aware, binary-safe, and redacted. Context packs persist manifests, source versions and hashes, redactions, token provenance, and freshness evidence without exposing excerpt content through inspection APIs.

## Assets

Asset records retain workspace-relative path, type/MIME conflict state, hash, source, provenance, license, metadata, usage, validation, and transform lineage. Downloads require URL safety, network/approval/workspace policy, bounded streaming, quarantine, and checksums. Collections reuse Asset IDs and never copy files silently.

## Research

Research connectors declare search/fetch/parse/cite capabilities, network permissions, and limits. URL policy blocks private and metadata endpoints and revalidates redirects. Queries distinguish factual retrieval from generation. Sources are hash-versioned; claims remain unsupported until linked to exact source excerpts.

## Orchestration and workflows

Outcome requests separate owner facts from assumptions. Approved blueprints and requirements compile into a dependency DAG. Assignment uses verified Agent capabilities and permissions. Context is prepared immediately before attempts. Dispatcher, fallback, parallel locks, approvals, and checkpoints enforce concurrency, spend, cancellation, and restart safety. Workflows use versioned typed DAG and node contracts; completion requires real node evidence.

## Quality and delivery

Acceptance criteria cannot pass without evidence or explicit waiver. Definition-of-Done requires completed dependencies, criteria, canonical run, and attempt evidence. Quality gates retain applicability, method, environment, findings, severity, and manual limitations. Deliverables trace requirements, assets, runs, and gates; packaging is deterministic, workspace-contained, and secret-blocking.

## Plugin catalogs

Catalog sources are disabled by default and bind an HTTPS index URL to an owner-selected Ed25519 public key. Canonical signed indexes support protocol-compatible plugins plus non-executable benchmark packs and workflow templates. Plugin install/update/remove/rollback requires scoped approval, permission review, SSRF-safe bounded downloads, ZIP and extracted-folder hashes, safe extraction, atomic version retention, and audit. Benchmark/workflow imports require scoped approval, signed package hashes, schema validation, source provenance, and remain non-executable until normal prerequisites are satisfied. Signature verification proves source integrity only; reputation remains unverified and no catalog entry becomes trusted automatically.

## API and frontend

Routes are assembled in `core/ai_fleet/api/routes.py` and mounted in `core/ai_fleet/main.py`. Frontend API types and clients are in `apps/web/src/services/api.ts`. Heavy routes and xterm are lazy-loaded from `apps/web/src/App.tsx`.

## Verification

Use `docs/QUALITY_GATES.md`. Roadmap status and known limitations are maintained in `docs/MASTER_EXECUTION_PLAN.md` and `docs/PRODUCT_GAP_ANALYSIS.md`.
