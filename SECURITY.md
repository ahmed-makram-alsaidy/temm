# Security Policy

## Supported versions

TEMM is pre-1.0 and under active development. Security fixes are applied to the current development line. No older release line is currently supported.

## Reporting

Do not publish credentials, exploit payloads containing private data, or user workspace content in a public issue.

**Intended private reporting channel:** GitHub Private Vulnerability Reporting via GitHub Repository Security Advisories. When the TEMM repository is public, use the "Report a vulnerability" button on the Security tab to submit a private advisory directly to maintainers.

This channel is not yet active because the repository has not been published. Until the repository is public and GitHub Private Vulnerability Reporting is enabled, retain sensitive evidence locally and contact the repository owner through available private communication.

A complete report should include affected version/commit, platform, reproduction steps, impact, trust boundary crossed, and a minimal redacted proof. Never include real API keys or unrelated user files.

## Response expectations

After a private channel is configured, maintainers should acknowledge a report within 7 days, provide an initial assessment within 14 days, and coordinate disclosure after a fix or mitigation is available. These are response targets, not guarantees. After the repository is public and GitHub Private Vulnerability Reporting is active, security advisories will be published through GitHub's coordinated disclosure workflow.

Reports should be triaged as critical, high, medium, or low based on exploitability, affected trust boundary, confidentiality/integrity/availability impact, required user interaction, and whether secrets or host execution are involved. Acknowledgement is not confirmation of severity or eligibility.

## Coordinated disclosure and incident handling

- Keep reporter identity and unredacted evidence limited to people handling the issue.
- Reproduce with disposable data and rotate any credential used during validation.
- Record affected versions, mitigations, regression tests, migration implications, and release checks.
- Do not publish exploit details before a fix or owner-approved mitigation is available unless active exploitation requires an earlier warning.
- Security fixes must not silently delete user data, weaken approvals, disable audit evidence, or claim rollback/deployment success without verification.
- After release, publish a redacted advisory through the owner-approved repository channel when one exists.

## Trust boundaries

The canonical threat model is `docs/SECURITY_THREAT_MODEL.md`. Important boundaries include:

- the browser to local REST/WebSocket server;
- approved Workspaces to the rest of the host filesystem;
- core to CLI/PTY subprocesses;
- core to provider/network adapters;
- core to out-of-process plugins;
- downloaded or imported content to trusted project assets;
- secret references to all logs, events, receipts, exports, and UI responses.

## Plugins

Plugins are untrusted until inspected and approved. Review source, signed-catalog identity where applicable, ZIP and extracted-folder hashes, entrypoint, protocol compatibility, requested permissions, and granted profile. Permission or package identity changes require reapproval. Marketplace install/update/remove/rollback requires scoped approvals and retained version integrity. Plugins execute out of process but are not a complete operating-system sandbox.

## Downloads and research

Network actions require policy and, where configured, approval. URL safety must block private, loopback, link-local, metadata, and non-global addresses and revalidate redirects. Downloads must enforce type, size, timeout, destination containment, quarantine, checksum, provenance, and license controls. Media transforms must use fixed argv allowlists, workspace-contained paths, input/output hashes, bounded subprocess lifecycle, atomic outputs, metadata validation, and retained lineage.

## Secrets

Use write-only secret references and operating-system-backed vault storage. Do not put secrets in prompts, URLs, command arguments, manifests, test fixtures, screenshots, issue reports, or repository files. Rotate any credential that may have been exposed.

## Scope limitations

Local-first does not mean risk-free. Agents, full-access profiles, provider requests, plugins, shell commands, and downloaded files can affect confidentiality and integrity. Container or VM sandboxing is not yet a general guarantee.
