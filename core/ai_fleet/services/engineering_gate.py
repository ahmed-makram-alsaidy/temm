import json
import os
from pathlib import Path
from typing import Any

from ..engine.process_manager import ProcessManager
from ..errors import DomainError


class EngineeringGateService:
    def discover(self, root: Path) -> list[dict]:
        checks = []
        package = root / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise DomainError("validation_failed", message="package.json is invalid.") from exc
            for kind, names in {"test": ["test"], "lint": ["lint"], "type": ["typecheck", "type-check"], "build": ["build"]}.items():
                name = next((item for item in names if item in scripts), None)
                if name:
                    npm = "npm.cmd" if os.name == "nt" else "npm"
                    checks.append({"kind": kind, "argv": [npm, "run", name], "source": "package.json", "script": scripts[name]})
        if (root / "pyproject.toml").is_file():
            checks.append({"kind": "configuration", "argv": None, "source": "pyproject.toml", "reason": "No command is inferred without repository instructions."})
        return checks

    async def run(self, manager: ProcessManager, root: Path, checks: list[dict], timeout_seconds: float = 600) -> list[dict]:
        results = []
        for index, check in enumerate(checks):
            if not check.get("argv"):
                results.append({**check, "status": "not_run", "evidence": check.get("reason")})
                continue
            receipt = await manager.execute_argv(check["argv"], f"engineering-gate-{index}", cwd=str(root), timeout_seconds=timeout_seconds)
            results.append({**check, "status": "passed" if receipt["success"] else "failed", "receipt": {key: value for key, value in receipt.items() if key not in {"stdout", "stderr"}}, "stdout": receipt["stdout"], "stderr": receipt["stderr"]})
        return results


engineering_gate_service = EngineeringGateService()
