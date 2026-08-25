# Reproducible Build Constraints

Frontend dependencies are integrity-locked by `apps/web/package-lock.json`. Python 3.12 dependencies are version- and SHA-256-locked separately for Windows x86-64 and Linux x86-64 in `requirements-lock-win.txt` and `requirements-lock-linux.txt`. `requirements.txt` remains the human-maintained lower-bound input and is not used by CI installation.

CI installs Python dependencies with `--require-hashes`, uses `npm ci`, verifies the Apache-2.0 repository policy and reviewed dependency-license inventory, generates CycloneDX-compatible dependency inventory with license expressions, build-input provenance, and SHA-256 checksum files twice, then compares both output directories. Release evidence excludes timestamps and machine-specific absolute paths so equivalent source inputs and declared environment values produce byte-identical evidence files.

Generate evidence locally:

```powershell
python -m core.ai_fleet.build_provenance --output build-evidence
```

The generated directory contains:

- `build-provenance.json` with checksummed lock/manifests and declared environment
- `sbom.cdx.json` with Python platform-lock and npm dependency components plus reported/reviewed license expressions
- `SHA256SUMS` covering both JSON evidence files

Frontend builds regenerate `apps/web/public/THIRD_PARTY_LICENSES.txt` from exact installed runtime package license files before Vite copies it into `dist`. Windows runtime ZIPs include the canonical `LICENSE`, the reviewed dependency inventory, and the frontend third-party license bundle. A project `NOTICE` is intentionally absent because no current verified notice obligation was found.

Current reproducibility claim is limited to dependency resolution for Python 3.12 on Windows/Linux x86-64, npm lock installation, deterministic delivery ZIPs, deterministic Windows runtime ZIP manifests, and deterministic release-evidence files. The Windows installer tooling validates package/file hashes, uses versioned installs and atomic launcher/state replacement, supports rollback, and preserves the explicit data root by default. A bit-for-bit application bundle across different operating systems, CPU architectures, Python/Node versions, or toolchain versions is not claimed. Compiled native installer packaging and clean-VM install/update/uninstall verification remain release blockers.

When direct requirements change, regenerate both lock files from clean target-platform resolver reports, retain exact artifact hashes, run hash-only download/install validation, and review transitive version changes before merge.
