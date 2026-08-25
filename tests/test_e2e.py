"""Trust-oriented smoke checks for the current AI Fleet OS foundation."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ai_fleet.engine.benchmark_engine import benchmark_engine
from core.ai_fleet.engine.workflow_engine import workflow_engine
from core.ai_fleet.main import app
from core.ai_fleet.storage.database import init_db


async def expect_disabled(coro, feature: str) -> None:
    try:
        await coro
    except RuntimeError as exc:
        assert "disabled" in str(exc).lower()
        print(f" -> {feature}: safely disabled")
        return
    raise AssertionError(f"{feature} unexpectedly returned a synthetic result")


async def run_tests() -> None:
    print("[1/7] Initializing schema without demo execution records...")
    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        print("[2/7] Checking honest fleet readiness metrics...")
        response = await client.get("/api/fleet/overview")
        assert response.status_code == 200
        overview = response.json()["fleet_counts"]
        assert overview["models_online"] <= overview.get("models_registered", overview["models_online"])
        assert overview["providers_count"] <= overview.get("providers_registered", overview["providers_count"])

        print("[3/7] Checking workspace boundary and execution preflight...")
        response = await client.get("/api/workspaces")
        assert response.status_code == 200
        workspaces = response.json()
        response = await client.post(
            "/api/tasks/preflight",
            json={"prompt": "Fix a React bug in this repository.", "routing_mode": "balanced"},
        )
        assert response.status_code == 200
        preflight = response.json()
        if not workspaces and preflight.get("selected_agent"):
            assert preflight["can_execute"] is False
            assert any(blocker["code"] == "workspace_required" for blocker in preflight["blockers"])

        print("[4/7] Checking read-only version probe and command audit API...")
        response = await client.post(
            "/api/terminal/run",
            json={"command": "python --version", "shell": "powershell"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        response = await client.post(
            "/api/terminal/run",
            json={"command": "Get-ChildItem", "shell": "powershell"},
        )
        assert response.status_code == 400
        response = await client.get("/api/terminal/history")
        assert response.status_code == 200

        print("[5/7] Checking plugin registry API...")
        response = await client.get("/api/plugins")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

        print("[6/7] Verifying fake execution endpoints stay locked...")
        response = await client.post(
            "/api/benchmarks/run",
            json={"benchmark_id": "bench-coding", "model_ids": ["gpt-4o"]},
        )
        assert response.status_code == 501
        response = await client.post(
            "/api/workflows/run",
            json={"workflow_id": "workflow-full-review", "input_text": "Review this change"},
        )
        assert response.status_code in {404, 422}, f"Workflow run should fail gracefully, got {response.status_code}"

    print("[7/7] Verifying internal engines cannot bypass the locks...")
    await expect_disabled(
        benchmark_engine.run_benchmark_suite("bench-coding", ["gpt-4o"]),
        "Benchmark runner",
    )
    await expect_disabled(benchmark_engine.get_blind_arena_pair(), "Blind arena")
    await expect_disabled(
        workflow_engine.execute_workflow("workflow-full-review", "Review this change"),
        "Workflow runner",
    )
    print("\nAll trust-oriented smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(run_tests())
