# Repository Quality Gates

Run from repository root unless a working directory is specified. A coherent checkpoint requires all applicable gates to pass; warnings are recorded honestly.

| Gate | Command | Working directory | Required |
|---|---|---|---|
| License policy | `python -m core.ai_fleet.license_policy` | root after `npm ci` | Yes |
| Python compile | `python -m compileall -q core tests` | root | Yes |
| Focused backend tests | `python -m unittest <relevant modules> -v` | root | Yes per slice |
| Full backend tests | `python -m unittest discover -s tests -p "test_*.py"` | root | Yes |
| Trust/API smoke | `python tests/test_e2e.py` | root | Yes |
| Frontend lint | `npm run lint` | `apps/web` | Yes for frontend changes |
| TypeScript | `npx tsc -b --pretty false` | `apps/web` | Yes for frontend/API type changes |
| Production build | `npm run build` | `apps/web` | Yes for frontend changes |
| Browser UX gates | `.\tools\quality\browser-gates.ps1` | repository root on Windows with Chrome/Edge | Yes for shell/UX/theme/responsive changes |
| Diff whitespace | `git diff --check` | root | Yes |
| Startup/API/SPA | Start Uvicorn on a temporary localhost port, probe changed API + SPA, terminate PID, verify exit. | root | Yes for API/startup slices |
| SQLite integrity/schema | `PRAGMA integrity_check` plus required-column assertions. | root | Yes for database changes |
| Security review | Apply `SECURITY_THREAT_MODEL.md` checklist and run abuse/leakage tests. | root | Yes |

## Gate rules

- Do not assume a test framework or command not present in this file/repository.
- Targeted tests run before the full suite.
- A warning is not a pass/fail unless the tool exits nonzero, but warnings must be recorded and triaged.
- Current accepted technical debt: pywinpty internal `ResourceWarning` after verified parent/child termination; frontend bundle warning from xterm/detail UI. Neither is ignored if behavior regresses.
- Startup smoke must clean the spawned server in `finally` and verify the process exited.
- Test output must not contain real secrets.
- Never skip hooks, tests, or checks to obtain a green result.
