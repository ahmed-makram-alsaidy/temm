# Versioning and Compatibility

## Product version

AI Fleet OS is pre-1.0. Product releases use Semantic Versioning:

- Patch: compatible fixes and documentation.
- Minor: additive features and compatible schemas/protocols.
- Major: incompatible API, persisted schema, plugin/provider protocol, or behavior changes.

Before 1.0, a minor release may contain a documented incompatibility only when an upgrade path and deprecation notice are provided.

## Contract versions

| Contract | Current | Compatibility rule |
|---|---:|---|
| Domain schema | 1.0 | Additive fields within 1.x; removed/changed semantics require 2.0. |
| Capability schema | 1.0 | Additive capabilities within 1.x; aliases must be documented; unknown values rejected. |
| State schema | 1.0 | New states may be additive; clients must handle unknown states; transition changes require review. |
| Error schema | 1.0 | Codes and meanings stable within 1.x; additive details allowed. |
| Event schema | 1.0 | Additive payload fields allowed; event meaning/removal requires major version. |
| Plugin protocol | 1.0 / requirement 1.x | Core negotiates declared compatibility; incompatible plugins remain unloaded. |
| Provider protocol | 1.0 | Exact current protocol required until a negotiated range contract is introduced. |
| Settings schema | 1.0 | Additive keys with defaults allowed; key meaning/type changes require major version. |
| SQLite schema | migration 41 | Forward-only checksummed migrations with pre-migration backup and failure restoration. |

## Deprecation

1. Mark the route, field, state, capability, or protocol as deprecated in code/OpenAPI and documentation.
2. Provide the replacement and migration instructions.
3. Retain compatible behavior for at least one minor release where safety permits.
4. Remove only in a major release, except security vulnerabilities or behavior that fabricates evidence.
5. Security removal notes must document the break and safe alternative.

## Persisted data upgrades

- Never edit an applied migration checksum.
- Add a new migration and test legacy upgrade, idempotency, backup, and restoration.
- Preserve execution, audit, financial, provenance, decision, and revision history.
- No automatic downgrade is promised. Rollback restores the pre-migration backup when migration application fails.

## Plugin/provider upgrade path

- Manifests declare protocol compatibility.
- Core inspects package identity/hash and permissions before load.
- Incompatible packages remain registered but unloaded with an explicit reason.
- Permission or identity changes require reapproval.
- Hot reload cannot mutate active invocations.

## API clients

Clients should use OpenAPI, stable error codes, explicit schema versions, and tolerate additive fields. Unknown evidence remains unknown; clients must not coerce it to zero or success.
