#!/usr/bin/env python3
"""Contributor setup verification for TEMM.

Run from repository root after following CONTRIBUTING.md setup steps.
Reports pass/fail for each required gate without modifying repository state.
"""

import json
import subprocess
import sys
from pathlib import Path


def check(name: str, cmd: list[str], cwd: str | None = None, timeout: int = 120) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        passed = result.returncode == 0
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed and result.stderr:
            for line in result.stderr.strip().splitlines()[:5]:
                print(f"         {line}")
        return passed
    except FileNotFoundError:
        print(f"  [FAIL] {name} — command not found: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [FAIL] {name} — timed out after {timeout}s")
        return False


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    web = root / "apps" / "web"
    results: list[bool] = []

    print("TEMM contributor setup verification")
    print("=" * 50)
    print()

    # Python
    print("Python environment:")
    results.append(check("Python version", [sys.executable, "--version"]))
    results.append(check("Import core package", [sys.executable, "-c", "import core.ai_fleet.main"]))
    results.append(check("Compile check", [sys.executable, "-m", "compileall", "-q", "core", "tests", "tools", "sdk", "aifleet_sdk"]))
    print()

    # Frontend
    print("Frontend environment:")
    results.append(check("Node.js version", ["node", "--version"]))
    results.append(check("npm ci (integrity)", ["npm", "ci"], cwd=str(web)))
    results.append(check("Lint", ["npm", "run", "lint"], cwd=str(web)))
    results.append(check("TypeScript", ["npx", "tsc", "-b", "--pretty", "false"], cwd=str(web)))
    results.append(check("Production build", ["npm", "run", "build"], cwd=str(web), timeout=180))
    print()

    # License
    print("License verification:")
    results.append(check("License policy", [sys.executable, "-m", "core.ai_fleet.license_policy"]))
    print()

    # Backend tests
    print("Backend tests:")
    results.append(check("Unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], timeout=300))
    results.append(check("E2E smoke", [sys.executable, "tests/test_e2e.py"], timeout=60))
    print()

    # Database
    print("Database:")
    results.append(check("Migrations", [sys.executable, "-m", "unittest", "tests.test_migrations", "-v"], timeout=30))
    print()

    # Summary
    passed = sum(results)
    total = len(results)
    print("=" * 50)
    print(f"Results: {passed}/{total} passed")
    if passed == total:
        print("Contributor setup is VERIFIED.")
        return 0
    else:
        print(f"FAILED: {total - passed} check(s) did not pass.")
        print("Review CONTRIBUTING.md for setup requirements.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
