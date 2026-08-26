# Local API

AI Fleet OS exposes a local FastAPI application. The generated OpenAPI document at `/openapi.json` is the route/schema source of truth. This guide explains stable conventions and primary boundaries.

## Base and versioning

Default base: `http://127.0.0.1:8787` or the configured local port.

Domain, error, event, provider, and plugin contracts expose explicit schema/protocol versions. API compatibility is currently pre-1.0; clients must tolerate additive response fields.

## Request safety

Browser requests require an allowed local Host and Origin. Native local clients may omit Origin. Request bodies and WebSocket messages are bounded. Secret values are write-only and redacted from errors, events, receipts, audit, and exports.

## Response conventions

Successful responses include request metadata headers. Bounded list endpoints expose count/cursor headers where implemented. Validation failures use HTTP 422. Conflicts use 409. Missing resources use 404. Execution unavailable uses its registered taxonomy status.

Canonical error payload:

```json
{
  "error": {
    "schema_version": "1.0",
    "code": "validation_failed",
    "message": "Request validation failed.",
    "retryable": false,
    "details": {}
  },
  "request_id": "..."
}
```

Some legacy routes also retain `detail` for compatibility.

## Health

- `GET /health/live`: minimal process liveness.
- `GET /health/ready`: database integrity/migrations, frontend build, Agent and PTY readiness evidence.

## Fleet registries

- `/api/models`: model lifecycle and evidence. Pricing, capability, availability, baseline, favorites, and history have nested routes.
- `/api/agents`: executable Agent lifecycle, auth checks, rescans, and write-only secret references.
- `/api/providers`: provider instances, health, model ingestion, quota, and secret references.
- `/api/plugins`: inspection, registration, reload, invocation, cancellation, and conformance.
- `/api/scanner`: manifest-driven local CLI discovery.

A Model is not an Agent. Provider configuration alone does not prove model availability.

## Runs

- `GET /api/runs`: bounded canonical run history.
- `GET /api/runs/{id}`: lifecycle and financial evidence.
- Nested: attempts, events, output, artifacts, usage, latency, efficiency.
- `POST /api/runs/{id}/cancel`: cancellation request and active executor cancellation.
- `GET /api/runs/compare?run_id=...`: compares only commensurable evidence.

Unknown financial values are `null`, not zero. Formula, currency, price record, and provenance are retained under `financials`.

## Projects

- `/api/projects`: create/list/update/archive/restore. Hard deletion is intentionally blocked.
- Nested: Workspaces, Project Brain facts/revisions, decisions, requirements, blueprints, context packs, research, assets, quality, value, plan, and deliverables.

Projects are outcome identities. Workspaces are approved filesystem roots.

Example:

```http
POST /api/projects
Content-Type: application/json

{
  "name": "Clinic CRM",
  "slug": "clinic-crm",
  "purpose": "Manage clinic operations",
  "project_type": "business_system",
  "owner": "local_owner"
}
```

## Assets and research

- `/api/assets`: project/global asset records and detail with usage, variants, and findings.
- `/api/asset-library`: persisted logical collections; membership never copies files.
- Project research responses include query policy/usage, source versions/freshness/confidence, claims, and exact citations. Unsupported claims remain visible.

Network/download connectors must apply URL SSRF policy, limits, approvals, and workspace containment.

## Benchmarks, Arena, and workflows

Versioned benchmark suite/pack routes coexist with a locked legacy synthetic route. Real CLI benchmark runs persist canonical runs/attempts and measured evaluator evidence.

Arena sessions are created from two completed real runs. Identity is hidden until a single vote.

Workflow definitions are typed DAGs. The workflow runner accepts only real node evidence. Legacy simulated workflow completion remains disabled.

## Orchestration

- `POST /api/orchestrations`: create durable state.
- `GET /api/orchestrations/{id}`: status/checkpoint.
- `POST /api/orchestrations/{id}/{action}`: analyze, plan, approve, start, pause, resume, cancel.

Commands are idempotent when already in the target state. Invalid transitions return stable conflict errors.

## Analytics and exports

- `/api/analytics/summary`: bounded UTC range; optional internal project scoping.
- `/api/analytics/export`: redacted JSON/CSV without prompts, outputs, secrets, receipts, or paths.
- `/api/budgets`: typed fleet/workspace/provider budgets and evidence-separated status.

Provider-reported, measured, estimated, and unknown values are never silently combined.

## WebSockets

Terminal WebSocket routes enforce local Origin/Host policy, bounded messages, persistent cursor replay, stdin/resize/cancel controls, and real PTY capability checks. Event payloads include correlation and sequence evidence. See `core/ai_fleet/main.py` and generated OpenAPI/route source for the configured path.

## Client examples

```python
import httpx

with httpx.Client(base_url="http://127.0.0.1:8787") as client:
    readiness = client.get("/health/ready").json()
    projects = client.get("/api/projects").json()
```

Never place provider keys in request logs or command arguments. Use write-only secret-reference routes.

## Headless CLI

Run from the repository root:

```powershell
python aifleet.py --json project list
python aifleet.py project create "Clinic CRM" clinic-crm --goal "Run the clinic's daily operations from one place" --type business_system
python aifleet.py run inspect <run-id>
python aifleet.py run cancel <run-id>
python aifleet.py workflow status <orchestration-id>
python aifleet.py workflow pause <orchestration-id>
python aifleet.py inspect fleet
```

Success exits 0. Typed API/client errors exit 2. JSON mode writes machine-readable output.

`project create` requires `--goal`: a TEMM project is the record of something a person wants
accomplished, and the blueprint, requirements, plan and acceptance are all derived from it.
A headless create with no goal never prompts and never substitutes one - it exits 2 and
writes `{"error": {"code": "goal_required", ...}}` to stderr. The user-facing word is
`goal`; the backend persists it in the project's existing `purpose` field.

## Python SDK distribution

The distributable SDK is isolated under `sdk/` and does not include backend modules:

```powershell
python -m pip install .\sdk

aifleet --base-url http://127.0.0.1:8787 --json inspect fleet
```

The SDK is not published to PyPI (`pip install temm-sdk` does not work); the only supported
install path is this in-repository source install, which produces the `temm` and `aifleet`
console commands declared by `sdk/pyproject.toml`.

Public imports use `from aifleet_sdk import AiFleetClient, AiFleetSdkError, AiFleetValidationError`. The client negotiates the domain schema before normal commands and maps timeout, connection, HTTP, and invalid-JSON failures to typed SDK errors. A call the client refuses itself raises `AiFleetValidationError`, which subclasses `ValueError` and carries a `code`; no request is sent. `create_project(name, slug, project_type, goal, ...)` requires a non-empty `goal` and raises `AiFleetValidationError("goal_required")` without it - the earlier `purpose=` keyword is still accepted as an alias for wire compatibility. No package publication is currently claimed.
