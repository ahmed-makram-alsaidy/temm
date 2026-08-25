import json
import uuid
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..engine.process_manager import ProcessManager, process_manager
from ..errors import DomainError
from ..permissions import permission_policy
from ..storage.models import AgentRecord, BenchmarkSuiteVersionRecord, TaskRun, WorkspaceRecord
from .benchmark_suites import BenchmarkSuiteService
from .latency import latency_service
from .run_output import run_output_service
from .runs import run_lifecycle_service
from .rule_evaluators import rule_evaluator_service


class BenchmarkRunnerService:
    def __init__(self, manager: ProcessManager):
        self._manager = manager
        self._suites = BenchmarkSuiteService()

    async def run(self, session: AsyncSession, version_id: str, agent_id: str, workspace_id: str, timeout_seconds: float = 120, execution_id: str | None = None) -> Dict[str, Any]:
        version = await session.get(BenchmarkSuiteVersionRecord, version_id)
        agent = await session.get(AgentRecord, agent_id)
        workspace = await session.get(WorkspaceRecord, workspace_id)
        if not version or not agent or not workspace:
            raise DomainError("resource_not_found", message="Benchmark version, Agent, or workspace was not found.")
        if agent.discovery_state != "verified" or agent.status != "ready" or not agent.user_enabled or agent.lifecycle_status != "active" or agent.auth_state not in {"not_required", "verified"}:
            raise DomainError("resource_conflict", message="Benchmark Agent is not verified and ready.")
        if agent.supports_interactive or agent.input_method not in {"argument", "stdin"}:
            raise DomainError("validation_failed", message="Canonical benchmark runner currently supports non-interactive argument/stdin Agents only.")
        required = {"shell"}
        if not permission_policy.allows(agent.permission_profile, required) or not permission_policy.allows(workspace.permission_profile, required):
            raise DomainError("permission_denied", message="Agent and workspace profiles must allow shell execution.")
        cases = await self._suites.cases(session, version_id)
        results = []
        for index, case in enumerate(cases, start=1):
            run_id = f"{execution_id}-{index}" if execution_id else f"benchmark-{uuid.uuid4().hex[:12]}"
            await run_lifecycle_service.create(session, run_id=run_id, prompt=case.prompt, routing_mode="benchmark", workspace_id=workspace_id)
            await run_lifecycle_service.start(session, run_id)
            attempt = await run_lifecycle_service.start_attempt(session, run_id, "cli", agent_id=agent_id)
            chunks: List[Dict[str, str]] = []
            async def on_chunk(text: str, stream: str):
                chunks.append({"stream": stream, "content": text})
            receipt = await self._manager.execute_argv(self._argv(agent, case.prompt, workspace.path), task_id=run_id, cwd=workspace.path if agent.working_directory == "workspace" else None, timeout_seconds=timeout_seconds, on_chunk=on_chunk, stdin_data=case.prompt if agent.input_method == "stdin" else None)
            for chunk in chunks:
                await run_output_service.append(session, run_id, chunk["stream"], chunk["content"], attempt.id)
            status = "completed" if receipt["success"] else "cancelled" if receipt["outcome"] == "cancelled" else "timed_out" if receipt["outcome"] == "timed_out" else "failed"
            receipt_evidence = {key: value for key, value in receipt.items() if key not in {"stdout", "stderr"}}
            receipt_evidence.update({"suite_version_id": version_id, "case_id": case.id, "case_key": case.case_key, "content_hash": version.content_hash})
            await latency_service.record(session, {"run_id": run_id, "attempt_id": attempt.id, "duration_ms": receipt["duration_ms"], "source": "measured", "method": "process_wall_clock"})
            await run_lifecycle_service.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt=receipt_evidence, error_code=receipt.get("error_code"))
            await run_lifecycle_service.finalize(session, run_id, status, receipt.get("error_code"))
            evaluation = None
            if status == "completed" and case.evaluator_type in {"exact", "regex", "json_schema"}:
                config = json.loads(case.evaluator_config or "{}")
                if case.evaluator_type == "exact" and "expected" not in config:
                    config["expected"] = case.expected_behavior
                evaluation = rule_evaluator_service.evaluate(case.evaluator_type, receipt.get("stdout", ""), config)
            score = evaluation["score"] if evaluation else None
            score_provenance = evaluation["provenance"] if evaluation else "unknown"
            run = await session.get(TaskRun, run_id)
            run.selected_agent_id = agent_id
            run.task_type = f"benchmark:{version.category}"
            run.duration_ms = receipt["duration_ms"]
            run.latency_provenance = "measured"
            run.quality_eval_score = score
            run.quality_provenance = score_provenance
            run.measurement_metadata = json.dumps({"benchmark": {"suite_version_id": version_id, "case_id": case.id, "case_key": case.case_key, "content_hash": version.content_hash}, "evaluation": evaluation or {"score": None, "provenance": "unknown", "reason": "not_evaluated"}})
            await session.commit()
            results.append({"case_id": case.id, "case_key": case.case_key, "run_id": run_id, "attempt_id": attempt.id, "status": status, "score": score, "score_provenance": score_provenance})
        return {"suite_version_id": version_id, "content_hash": version.content_hash, "agent_id": agent_id, "workspace_id": workspace_id, "cases": results, "scores_computed": any(item["score"] is not None for item in results)}

    def _argv(self, agent: AgentRecord, prompt: str, workspace: str) -> List[str]:
        executable = agent.detected_path or agent.cli_command
        args = json.loads(agent.invocation_args or "[]")
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            raise DomainError("validation_failed", message="Agent invocation arguments are invalid.")
        rendered = [item.replace("{prompt}", prompt).replace("{workspace}", workspace) for item in args]
        if agent.input_method == "argument" and not any("{prompt}" in item for item in args):
            rendered.append(prompt)
        return [executable, *rendered]


benchmark_runner_service = BenchmarkRunnerService(process_manager)
