# Licensing Policy

## First-party work

TEMM first-party source code and documentation are licensed under the Apache License 2.0. The canonical license text is `LICENSE`; the SPDX identifier is `Apache-2.0`.

The standalone Python SDK is distributed from `sdk/`. Its `sdk/LICENSE` file is an exact packaging copy of the canonical root license and must remain byte-identical.

No project `NOTICE` file is currently included because the repository audit found no first-party attribution notice or inherited Apache NOTICE content that requires one. Add a NOTICE only when a verified attribution obligation requires it; never use NOTICE as a substitute for third-party license text.

## Third-party software and assets

Apache-2.0 applies only to first-party work. Dependencies, bundled fonts, icons, sample assets, generated artifacts, and other third-party material remain under their respective licenses. Nothing in this repository relicenses third-party material.

Frontend runtime dependencies are integrity-locked in `apps/web/package-lock.json`. The production build emits `THIRD_PARTY_LICENSES.txt` from the exact installed runtime packages so distributed JavaScript, icons, and fonts retain upstream copyright and license text. The current bundled fonts are Alexandria and Manrope under `OFL-1.1`; their font software remains under that license.

Python dependencies are installed as separate distributions from hash-locked requirements. Their own package metadata and included license files remain authoritative. Release SBOM generation preserves dependency license identifiers reported by the npm lock and by the maintained Python license inventory.

Project assets acquired by users are not covered by the repository license. AI Fleet asset records retain independent provenance and license state; unknown-license material is not represented as commercially safe.

## Contributions

Unless explicitly marked otherwise, contributions intentionally submitted for inclusion are provided under Apache-2.0 as described by section 5 of the license. Contributors must not submit material they lack the right to contribute and must preserve applicable third-party notices.

## Release checks

The license gate verifies:

- the canonical Apache-2.0 text and SPDX declarations;
- exact equality of root and SDK license copies;
- README and licensing-policy claims;
- dependency license metadata for every locked frontend runtime package;
- exact upstream license text availability before frontend distribution;
- inclusion of `LICENSE` and `THIRD_PARTY_LICENSES.txt` in Windows runtime packages;
- SBOM license identifiers where source metadata supplies them.
