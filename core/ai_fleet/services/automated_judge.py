import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..judges import JudgeProvenance, JudgeRequest, JudgeResult, JudgeType
from ..storage.models import JudgeExecutionRecord
from .provider_runtime import ProviderRuntimeRegistry


class AutomatedJudgeService:
    def __init__(self, registry: ProviderRuntimeRegistry):
        self._registry = registry

    async def execute(self, session: AsyncSession, request: JudgeRequest, provider: str, model_id: str) -> JudgeExecutionRecord:
        request.validate()
        if request.judge_type != JudgeType.MODEL:
            raise DomainError("validation_failed", message="Automated model judge requires model judge type.")
        execution = JudgeExecutionRecord(id=f"judge-{uuid.uuid4().hex[:12]}", request_id=request.request_id, judge_type="model", provider=provider, model_id=model_id, status="running", provenance="model_opinion")
        session.add(execution)
        await session.commit()
        prompt = self._prompt(request)
        chunks = []
        error_code = None
        adapter = self._registry.resolve(provider)
        try:
            async for event in adapter.stream(model_id, prompt, execution.id):
                if event.event_type == "chunk":
                    chunks.append(event.text)
                elif event.event_type in {"error", "cancelled"}:
                    error_code = event.error_code or event.event_type
                    break
            raw = "".join(chunks).strip()
            execution.raw_output_hash = hashlib.sha256(raw.encode()).hexdigest() if raw else None
            if error_code:
                raise DomainError("execution_failed", message="Judge provider execution failed.", details={"error_code": error_code})
            if len(raw.encode()) > 1_000_000:
                raise DomainError("validation_failed", message="Judge output exceeds the 1 MiB limit.")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
            result = JudgeResult(request_id=request.request_id, judge_type=JudgeType.MODEL, provenance=JudgeProvenance.MODEL_OPINION, winner_candidate_id=payload.get("winner_candidate_id"), scores={key: float(value) for key, value in payload.get("scores", {}).items()}, rationale=str(payload.get("rationale", "")), confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None, method="blind_model_judge_v1", evidence={"provider": provider, "model_id": model_id, "criteria": request.criteria}).validate([candidate.candidate_id for candidate in request.candidates])
            execution.status = "completed"
            execution.result_json = json.dumps(result.to_dict())
            execution.completed_at = datetime.utcnow()
        except (DomainError, json.JSONDecodeError, ValueError, TypeError) as exc:
            execution.status = "failed"
            execution.error_code = error_code or (exc.code if isinstance(exc, DomainError) else "invalid_judge_output")
            execution.result_json = json.dumps({"ground_truth": False, "provenance": "model_opinion", "error": execution.error_code})
            execution.completed_at = datetime.utcnow()
        await session.commit()
        return execution

    def _prompt(self, request: JudgeRequest) -> str:
        payload = request.public_payload()
        return "Evaluate anonymous candidates. Candidate order has no meaning. Use only the stated criteria. Return one JSON object with winner_candidate_id (or null), scores keyed by candidate id from 0 to 100, rationale, and confidence from 0 to 1. Do not claim ground truth.\n" + json.dumps(payload, ensure_ascii=False)
