import json
import uuid
from collections import Counter
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import JudgeConsensusRecord, JudgeExecutionRecord


class JudgeConsensusService:
    async def aggregate(self, session: AsyncSession, request_id: str, threshold: float = 2 / 3) -> JudgeConsensusRecord:
        if not 0.5 < threshold <= 1:
            raise DomainError("validation_failed", message="Consensus threshold must be greater than 0.5 and at most 1.")
        rows = (await session.execute(select(JudgeExecutionRecord).where(JudgeExecutionRecord.request_id == request_id, JudgeExecutionRecord.status == "completed").order_by(JudgeExecutionRecord.created_at, JudgeExecutionRecord.id))).scalars().all()
        if len(rows) < 2:
            raise DomainError("resource_conflict", message="At least two completed independent judges are required.")
        votes: List[str] = []
        judges = []
        for row in rows:
            payload = json.loads(row.result_json or "{}")
            winner = payload.get("winner_candidate_id")
            judges.append({"execution_id": row.id, "provider": row.provider, "model_id": row.model_id, "winner_candidate_id": winner, "confidence": payload.get("confidence"), "provenance": row.provenance})
            if winner:
                votes.append(winner)
        counts = Counter(votes)
        top = counts.most_common()
        tie = len(top) > 1 and top[0][1] == top[1][1]
        winner = top[0][0] if top and not tie else None
        agreement = top[0][1] / len(rows) if top and not tie else 0.0
        status = "consensus" if winner and agreement >= threshold else "escalation_required"
        result: Dict[str, Any] = {"algorithm": "majority-v1", "ground_truth": False, "judge_count": len(rows), "vote_count": len(votes), "vote_distribution": dict(sorted(counts.items())), "tie": tie, "disagreement": 1 - agreement, "judges": judges, "escalation_reason": None if status == "consensus" else "tie" if tie else "agreement_below_threshold"}
        record = JudgeConsensusRecord(id=f"consensus-{uuid.uuid4().hex[:12]}", request_id=request_id, algorithm="majority-v1", threshold=threshold, status=status, winner_candidate_id=winner if status == "consensus" else None, agreement=agreement, result_json=json.dumps(result))
        session.add(record)
        await session.commit()
        return record


judge_consensus_service = JudgeConsensusService()
