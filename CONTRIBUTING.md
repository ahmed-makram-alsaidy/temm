# Contributing to TEMM

Contributions are welcome while the project is in alpha. Read `README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_THREAT_MODEL.md`, and `docs/LICENSING.md` before changing behavior.

## License

By intentionally submitting a contribution for inclusion, you agree that it is provided under Apache-2.0 as described by section 5 of `LICENSE`. Only submit work you have the right to contribute. Do not copy third-party source or assets into the repository without preserving their license, copyright, provenance, and redistribution obligations.

## Local setup

Requirements:

- Python 3.12
- Node.js 22 and npm
- Windows for ConPTY/browser Windows gates; most backend/frontend gates also run on Linux

From the repository root:

```powershell
python -m pip install -r requirements.txt
```

From `apps/web`:

```powershell
npm ci
npm run build
```

Run the application from the repository root:

```powershell
python run.py
```

The application defaults to `http://localhost:8787`. Windows users may instead run `start.ps1` or `start.bat`.

## Verify setup

After completing the steps above, run the setup verification script:

```powershell
python tools/verify-setup.py
```

This checks Python imports, compilation, frontend build, license policy, backend tests, and migrations without modifying repository state.

## Engineering rules

- Preserve the capability-based domain boundaries in `docs/ARCHITECTURE.md`.
- Do not fabricate availability, benchmarks, prices, quotas, savings, provenance, or completion.
- Use argv arrays rather than shell command strings.
- Enforce workspace containment, permissions, approvals, input bounds, redaction, and cancellation.
- Add versioned migrations; never edit an applied migration checksum.
- Keep Models, Agents, Providers, Runtimes, Skills, Tasks, and Runs distinct.
- Add tests for success, failure, cancellation, security boundaries, and truthful unknown states where applicable.
- Record material architecture decisions using `docs/ADR_TEMPLATE.md`.

## Quality gates

Run targeted tests first, then the applicable full gates documented in `docs/QUALITY_GATES.md`:

```powershell
python -m core.ai_fleet.license_policy
python -m compileall -q core tests tools sdk aifleet_sdk
python -m unittest discover -s tests -p "test_*.py"
python tests/test_e2e.py
```

From `apps/web`:

```powershell
npm run lint
npx tsc -b --pretty false
npm run build
```

On Windows with Chrome or Edge, run:

```powershell
.\tools\quality\browser-gates.ps1
```

Before requesting review, run `git diff --check` and inspect the complete diff. Do not skip failing gates. Document warnings and environment-specific gates that could not be run.

## Pull requests

A pull request should:

- explain the user-visible problem and the chosen approach;
- identify security, migration, compatibility, and license impact;
- include exact tests and results;
- avoid unrelated formatting or generated files;
- update API, architecture, quality, and roadmap evidence when behavior changes;
- contain no credentials, private data, generated secrets, or unsupported success claims.

Use conventional, concise commit subjects consistent with repository history. Do not rewrite public history to hide review changes.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow `SECURITY.md`. The private reporting endpoint remains owner-managed release work; until it is published, avoid disclosing exploit details publicly.

## Current verification boundary

The documented commands pass in the current Windows development environment and CI declares Windows/Linux jobs. A clean-machine contributor setup has not yet been independently verified, so `OSS-004` remains PARTIAL until that evidence exists.
