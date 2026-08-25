# Changelog

All notable changes to TEMM are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Initial open-source release

### Added
- **Completion runtime core**: real process lifecycle management (timeout,
  cancellation, duplicate-ID protection, process-tree cleanup, execution
  receipts) with Windows ConPTY support and live terminal streaming.
- **Project pipeline**: goal → research → blueprint → requirements → task
  graph → parallel execution → quality gates → acceptance evidence →
  verification → deliverable convergence ("Closed Cell").
- **Honest evidence model**: every run carries provenance for cost, tokens,
  and quality (`reported` / `measured` / `estimated` / `unknown`); nothing is
  presented as accepted or verified unless measured acceptance says so.
- **Manifest-driven tool discovery** with safe argv probes, auth-evidence
  states, Windows shim handling, and rescan support.
- **TEMM visual system**: semantic token layer, bespoke work-graph primitives,
  causal motion laws (reduced-motion safe), acceptance/evidence hierarchy,
  global shell, and converged inner surfaces; full RTL (Arabic) support with
  a 12px typography floor.
- **Quality gates**: deterministic backend regression suite (849 tests),
  static design-contract gates, real-product capture harnesses, responsive /
  contrast / keyboard / accessibility browser smokes, reproducible build
  evidence, and CI on push/PR across Windows and Linux.
- **Local SDK** (`aifleet_sdk`) and reference plugin examples.

### Known limitations
- PTY backends are Windows-only today; Linux/macOS terminals fall back.
- Catalog/model claims remain `unknown` until backed by current evidence.
- The lazy `RunWorkspace` chunk (~366 kB gzip ~94 kB) still needs optimization.

[0.1.0]: https://github.com/ahmed-makram-alsaidy/temm/releases/tag/v0.1.0
