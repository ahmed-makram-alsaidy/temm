"""TEMM Staged Capability Tournament Runner.

Discovers available routes, filters by current evidence, and runs
staged probes through the full production dispatcher to qualify
routes for Child A.

Usage: python -m core.ai_fleet.services.run_capability_tournament
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import select, delete
from core.ai_fleet.storage.database import AsyncSessionLocal, engine
from core.ai_fleet.storage.models import (
    ModelRecord, ModelCapabilityEvidenceRecord, QuotaObservationRecord,
)
from core.ai_fleet.environment_discovery import discover_environment
from core.ai_fleet.services.external_environment import ExternalEnvironmentService
from core.ai_fleet.services.staged_capability_tournament import StagedCapabilityTournamentService
from core.ai_fleet.services.executor_capabilities import ExecutorCapabilityService


# Capabilities required by Child A
CHILD_A_REQUIRED = {"coding", "file_read", "file_write", "multi_file_edit", "dependency_management", "command_execution"}


async def discover_candidate_routes(session) -> list[dict]:
    """Discover currently available OpenCode routes, filtering by negative evidence."""
    now = datetime.utcnow()

    # Query active models from external tools
    discovered = (await session.execute(
        select(ModelRecord).where(
            ModelRecord.source_type == "external_tool",
            ModelRecord.source_uri == "opencode-cli",
            ModelRecord.lifecycle_status == "active",
            ModelRecord.is_active.is_(True),
        )
    )).scalars().all()

    # Check exhausted quotas
    quota_rows = (await session.execute(
        select(QuotaObservationRecord).where(QuotaObservationRecord.expires_at > now)
    )).scalars().all()
    exhausted_providers = {
        (row.provider_instance_id, row.scope)
        for row in quota_rows
        if row.remaining_value == 0
    }

    candidates = []
    for model in discovered:
        provider = model.provider
        model_name = model.id.split("/", 1)[1] if "/" in model.id else model.id

        # Check if exhausted
        is_exhausted = (
            (f"opencode:{provider}", model_name) in exhausted_providers or
            (f"opencode:{provider}", "*") in exhausted_providers
        )
        if is_exhausted:
            continue

        # Check current negative capability evidence (unexpired)
        evidence_rows = (await session.execute(
            select(ModelCapabilityEvidenceRecord).where(
                ModelCapabilityEvidenceRecord.model_id == model.id,
                ModelCapabilityEvidenceRecord.supported.is_(False),
            )
        )).scalars().all()

        # Filter to current (unexpired) negative evidence
        current_negative = [
            row for row in evidence_rows
            if row.expires_at is None or row.expires_at > now
        ]

        # A route with current negative evidence for any Child A capability is excluded
        negative_capabilities = {row.capability for row in current_negative}
        blocked_for_child_a = negative_capabilities & CHILD_A_REQUIRED

        candidates.append({
            "model_id": model.id,
            "provider": provider,
            "model_name": model_name,
            "availability_state": model.availability_state,
            "availability_expires_at": model.availability_expires_at,
            "current_negative_capabilities": sorted(negative_capabilities),
            "blocked_for_child_a": sorted(blocked_for_child_a),
            "eligible_for_tournament": len(blocked_for_child_a) == 0,
        })

    return candidates


async def run_tournament():
    """Main tournament execution."""
    print("=" * 60)
    print("TEMM STAGED CAPABILITY TOURNAMENT")
    print(f"Started: {datetime.utcnow().isoformat()}Z")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        # Step 1: Refresh environment to get current routes
        print("\n[1/4] Discovering environment...")
        inventory = discover_environment()
        await ExternalEnvironmentService().import_inventory(session, inventory)
        print(f"  Tools: {len(inventory.tools)}")
        print(f"  Providers: {len(inventory.providers)}")
        print(f"  Models: {len(inventory.models)}")

        # Step 2: Find tournament candidates
        print("\n[2/4] Evaluating candidate routes...")
        candidates = await discover_candidate_routes(session)
        print(f"  Total discovered routes: {len(candidates)}")

        eligible = [c for c in candidates if c["eligible_for_tournament"]]
        blocked = [c for c in candidates if not c["eligible_for_tournament"]]

        print(f"  Eligible for tournament: {len(eligible)}")
        for c in eligible:
            print(f"    - {c['model_id']} (availability: {c['availability_state']})")
        print(f"  Blocked by negative evidence: {len(blocked)}")
        for c in blocked:
            print(f"    - {c['model_id']} (blocked: {', '.join(c['blocked_for_child_a'])})")

        if not eligible:
            print("\n[RESULT] No eligible routes for tournament. Stopping.")
            return {"success": False, "reason": "no_eligible_routes", "candidates": candidates}

        # Step 3: Run staged tournament for each eligible route (fail fast)
        print("\n[3/4] Running staged probes...")
        tournament = StagedCapabilityTournamentService()
        results = []

        for candidate in eligible:
            model_id = candidate["model_id"]
            print(f"\n  Testing: {model_id}")
            print(f"  " + "-" * 40)

            try:
                result = await tournament.run_tournament(
                    session, model_id, timeout_per_stage=90,
                )
                results.append(result)

                for stage in result["stages"]:
                    status_icon = "PASS" if stage.get("passed") else "SKIP" if stage.get("skipped") else "FAIL"
                    print(f"    [{status_icon}] {stage['stage_id']}")
                    if not stage.get("passed") and not stage.get("skipped"):
                        if stage.get("error"):
                            print(f"         Error: {stage['error']}")
                        elif stage.get("acceptance"):
                            failed = [a for a in stage["acceptance"] if a.get("status") != "passed"]
                            for f in failed:
                                print(f"         Failed: {f.get('criterion_id')}")

                print(f"    Capabilities proven: {sorted(result.get('positive_capabilities', []))}")
                print(f"    Child A eligible: {result.get('all_required_for_child_a')}")

                if result.get("all_required_for_child_a"):
                    print(f"\n  [WINNER] {model_id} qualifies for Child A!")
                    break  # First winner is sufficient

            except Exception as exc:
                print(f"    [ERROR] Tournament failed: {exc}")
                results.append({"model_id": model_id, "error": str(exc)})

        # Step 4: Run command execution probe (independent of AI route)
        print("\n[4/4] Running deterministic command execution probe...")
        try:
            cmd_result = await tournament.run_command_probe(session, timeout_seconds=30)
            cmd_status = "PASS" if cmd_result.get("passed") else "FAIL"
            print(f"    [{cmd_status}] command_execution")
            if cmd_result.get("run_id"):
                print(f"         Run: {cmd_result['run_id']}")
        except Exception as exc:
            print(f"    [ERROR] Command probe failed: {exc}")
            cmd_result = {"passed": False, "error": str(exc)}

        # Summary
        print("\n" + "=" * 60)
        print("TOURNAMENT SUMMARY")
        print("=" * 60)
        winners = [r for r in results if r.get("all_required_for_child_a")]
        if winners:
            print(f"  Eligible routes for Child A: {len(winners)}")
            for w in winners:
                print(f"    - {w['model_id']}: {sorted(w['positive_capabilities'])}")
        else:
            print("  No route qualified for Child A.")
            print("  Per-route evidence:")
            for r in results:
                if "error" in r:
                    print(f"    - {r['model_id']}: ERROR: {r['error']}")
                else:
                    print(f"    - {r['model_id']}: proven={sorted(r.get('positive_capabilities', []))}, negative={sorted(r.get('negative_capabilities', []))}")

        print(f"\n  Command execution: {'PASS' if cmd_result.get('passed') else 'FAIL'}")
        print(f"\nCompleted: {datetime.utcnow().isoformat()}Z")

        return {
            "success": len(winners) > 0,
            "candidates": candidates,
            "results": results,
            "winners": winners,
            "command_probe": cmd_result,
        }


if __name__ == "__main__":
    result = asyncio.run(run_tournament())
    sys.exit(0 if result.get("success") else 1)
