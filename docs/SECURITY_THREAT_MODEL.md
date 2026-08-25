# Security Threat Model

## Scope and assumptions

AI Fleet OS is a local-first web application that can execute subprocesses, access approved project files, store encrypted secrets, call external providers, load future plugins, research external sources, and manage downloaded/transformed assets. Local does not mean trusted: a hostile website, malicious project, compromised executable, unsafe plugin, crafted path, or poisoned remote source may attack the service.

## Trust boundaries

1. Browser ↔ local HTTP/WebSocket API
2. API ↔ encrypted secret vault and SQLite
3. Core ↔ subprocess/PTY process trees
4. Core ↔ approved workspace filesystem
5. Core ↔ Provider and research networks
6. Core ↔ plugin/runtime process boundary
7. Project files ↔ asset/download quarantine
8. User approval ↔ dangerous, network, paid, destructive, and elevated actions

## Assets to protect

- vault values, environment credentials, provider tokens, cookies, and auth state
- user source code, documents, project memory, decisions, and assets
- filesystem outside approved workspaces
- process integrity and host availability
- run/audit evidence and financial truth
- plugin protocol and update integrity
- license/provenance records

## Threats, current mitigations, and required controls

| ID | Boundary | Threat | Current mitigation | Required control / linked task | Residual risk |
|---|---|---|---|---|---|
| T-001 | Browser/API | Malicious website invokes local dangerous API. | Local Host/Origin allowlists cover HTTP and WebSocket; dangerous actions use scoped, expiring, single-use approvals. | Optional local session token remains defense-in-depth. | Medium. |
| T-002 | API | Oversized payload/WebSocket frame exhausts memory or disk. | Global request/WebSocket limits, bounded Pydantic fields/lists, output retention limits, download/package/media caps. | Continue endpoint-specific fuzzing and backpressure work. | Medium. |
| T-003 | API/logs | Secrets leak through errors, events, receipts, exports, auth output. | Central recursive redaction covers events, process chunks/receipts, audit details and exports; secrets are write-only references. | Provider/plugin subprocesses can still emit unknown secret forms. | Medium. |
| T-004 | Vault | Plaintext/weak secret storage or accidental migration loss. | Windows DPAPI; encrypted fallback; no API values returned. | Namespaced refs, backup/recovery, platform review (`FND-011`, `FND-019`). | Medium. |
| T-005 | Subprocess | Command injection through shell strings/argv/shims. | Discovery/onboarding uses validated argv and ProcessManager; fixed shim launchers. | Eliminate remaining shell-string paths; permission policy (`FND-029`). | High. |
| T-006 | Subprocess | Hanging/orphaned parent or child after timeout/cancel/crash. | Unified pipe/PTY manager owns states, timeouts, cancellation, bounded shutdown, Windows tree cleanup and receipts; plugins run out of process. | OS/library ResourceWarnings and crash-between-checkpoint windows remain. | Medium. |
| T-007 | Filesystem | Path traversal, symlink/reparse escape, arbitrary host file access. | Central resolved-path containment, approved workspaces, permission profiles, safe archive extraction, transform/download destination checks. | Reparse-point coverage and future plugin file APIs require continued review. | Medium. |
| T-008 | Project | Malicious repository instructions coerce secret disclosure or destructive commands. | Context packs record redactions; dangerous/network/destructive/elevated actions use persisted scoped approvals and permission profiles. | Prompt-injection classification and stronger sandboxing remain incomplete. | High. |
| T-009 | Provider/network | SSRF, unsafe custom base URLs, redirects, internal metadata access. | URL policy requires HTTPS/global addresses, blocks metadata/internal hosts, bounds redirects/size/time, and revalidates chains; built-ins use fixed endpoints. | DNS rebinding between validation and connect requires connector-level pinning. | Medium. |
| T-010 | Plugin | Inspection/import executes arbitrary plugin code. | Inspection never imports code; strict manifest/hash/protocol/permission validation precedes one-shot out-of-process RPC with timeout/cancellation/conformance. | Process isolation is not an OS sandbox; full-profile plugins remain high trust. | High. |
| T-011 | Plugin/update | Supply-chain package/plugin substitution. | Hash-locked dependencies, deterministic SBOM/provenance, opt-in HTTPS catalog sources, Ed25519 canonical-index verification, ZIP/folder SHA-256 and size pins, SSRF/redirect/path/symlink/special-file limits, scoped approvals, explicit permission review, atomic version retention, rollback, removal, and audit. | Publisher reputation and signing-key governance remain owner/community responsibilities. | Medium; catalog signature does not make plugin code trusted. |
| T-012 | Downloads/assets | Malicious file, SVG script, decompression bomb, MIME confusion. | SSRF-safe bounded quarantine download, MIME/extension conflict state, checksum/provenance/license records, SVG sanitation, safe archive extraction, bounded FFmpeg transforms. | Antivirus integration and complex decoder vulnerabilities remain external concerns. | Medium. |
| T-013 | Research | Prompt injection or fabricated source is treated as project truth. | Research queries persist versioned sources, content hashes, claims, citations, confidence/status and project usage; unsupported claims stay visible. | Content-level prompt-injection detection remains incomplete. | High. |
| T-014 | Database | Schema upgrades corrupt user data or partially apply. | Forward-only checksummed migrations, pre-upgrade SQLite backup, per-migration transactions, bounded retention and failure restoration through migration 41. | No automatic downgrade; clean-machine/large-database validation remains. | Low. |
| T-015 | Audit | Attacker mutates/deletes evidence or hides security action. | Append-oriented redacted audit records cover approvals, registries, marketplace, benchmarks and key lifecycle actions; events have persistent sequences/cursors. | Local database owner can still modify evidence; external tamper sealing is absent. | Medium. |
| T-016 | Finance | Estimated costs/savings represented as actual money. | Product gap documents uncertainty. | Measurement provenance and taxonomy (`TEL-001`, `TEL-008`). | High product-trust risk. |
| T-017 | Auth | Executable presence incorrectly implies authenticated readiness. | Generic auth states/probes; UNKNOWN blocks routing. | Provider/Agent auth evidence expiry and secret relationships (`FND-012`, `PRV-004`). | Medium. |
| T-018 | Concurrency | Stale UI overwrites Agent configuration or security state. | Agent integer revision and 409 conflicts. | Extend optimistic concurrency to other mutable domains. | Medium. |

## Security invariants

- Unknown is never treated as verified.
- Secrets are never returned after write and never embedded in normal configuration.
- User-controlled commands are argv, not shell strings, unless an explicitly approved shell executor is required.
- Every file operation resolves through approved scope before access.
- Cancellation and timeout clean tested process trees.
- Plugin inspection never imports plugin code.
- Paid acquisition, elevated permissions, and destructive operations require explicit scoped approval.
- Remote content is untrusted data, not executable instruction or project truth.
- Security failures and waivers are evidence, not successful completion.

## Review checklist

For each meaningful slice verify: input bounds; authorization and workspace scope; argv/path handling; secret redaction; lifecycle cleanup; network effects; persistence/migration impact; evidence truthfulness; audit requirements; frontend error leakage; and tests for abuse cases.
