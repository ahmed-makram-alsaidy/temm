"""Model Lab metadata leaderboard with synthetic execution disabled."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..storage.database import AsyncSessionLocal
from ..storage.models import ArenaVoteRecord, ModelRecord


class BenchmarkEngine:
    """Expose registry estimates while refusing fabricated benchmark results."""

    async def get_personal_leaderboard(self, category: str = "all") -> List[Dict[str, Any]]:
        """Rank catalog metadata; these values are estimates, not measured runs."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ModelRecord).where(ModelRecord.is_active == True))
            models = result.scalars().all()

        ranked: List[Dict[str, Any]] = []
        for model in models:
            if category == "coding":
                primary_score = model.coding_score
            elif category == "reasoning":
                primary_score = model.reasoning_score
            elif category == "arabic":
                primary_score = model.arabic_score
            elif category == "vision":
                primary_score = model.vision_score
            elif category == "speed":
                primary_score = model.speed_score
            elif category == "value":
                average_cost = max((model.input_cost_per_m + model.output_cost_per_m) / 2.0, 0.05)
                primary_score = min(100.0, (model.quality_score / average_cost) * 2.2) if not model.is_free else 99.5
            else:
                primary_score = model.quality_score

            average_cost = max((model.input_cost_per_m + model.output_cost_per_m) / 2.0, 0.05)
            value_score = min(99.9, (model.quality_score / average_cost) * 2.0) if not model.is_free else 99.9
            badges: List[str] = []
            if model.is_free:
                badges.append("Best Free" if model.quality_score > 90 else "Free Tier")
            if model.is_local:
                badges.append("100% Local / Private")
            if model.quality_score >= 97.0:
                badges.append("Frontier Quality")
            if model.tokens_per_sec >= 140.0:
                badges.append("Ultra Fast")
            if value_score >= 90.0:
                badges.append("Exceptional Value")

            ranked.append({
                "model_id": model.id,
                "name": model.name,
                "provider": model.provider,
                "score": round(primary_score, 1),
                "quality_score": round(model.quality_score, 1),
                "coding_score": round(model.coding_score, 1),
                "reasoning_score": round(model.reasoning_score, 1),
                "arabic_score": round(model.arabic_score, 1),
                "vision_score": round(model.vision_score, 1),
                "speed_score": round(model.speed_score, 1),
                "tokens_per_sec": round(model.tokens_per_sec, 0),
                "reliability_score": round(model.reliability_score, 1),
                "value_score": round(value_score, 1),
                "input_cost_per_m": model.input_cost_per_m,
                "output_cost_per_m": model.output_cost_per_m,
                "is_local": model.is_local,
                "is_free": model.is_free,
                "badges": badges,
                "best_for": json.loads(model.best_for) if isinstance(model.best_for, str) else model.best_for,
                "not_ideal_for": json.loads(model.not_ideal_for) if isinstance(model.not_ideal_for, str) else model.not_ideal_for,
                "evidence": "registry_estimate",
            })

        ranked.sort(key=lambda item: item["score"], reverse=True)
        for index, item in enumerate(ranked):
            item["rank"] = index + 1
        return ranked

    async def run_benchmark_suite(self, benchmark_id: str, model_ids: List[str]) -> Dict[str, Any]:
        """Reject benchmark runs until real executors and a judge are connected."""
        raise RuntimeError(
            "Simulated benchmark scoring is disabled. Connect real model executors "
            "and an evaluation judge before running a benchmark suite."
        )

    async def get_blind_arena_pair(self, prompt: Optional[str] = None) -> Dict[str, Any]:
        """Reject arena pairs until two real model responses are available."""
        raise RuntimeError(
            "The synthetic arena is disabled. Connect two real executors before "
            "creating a blind comparison."
        )

    async def submit_arena_vote(
        self,
        arena_id: str,
        prompt: str,
        model_a_id: str,
        model_b_id: str,
        winner: str,
    ) -> Dict[str, Any]:
        """Record a vote only for a real arena session supplied by the caller."""
        async with AsyncSessionLocal() as session:
            vote = ArenaVoteRecord(
                id=arena_id,
                prompt=prompt,
                model_a_id=model_a_id,
                model_b_id=model_b_id,
                winner=winner,
            )
            session.add(vote)
            await session.commit()
            model_a = await session.get(ModelRecord, model_a_id)
            model_b = await session.get(ModelRecord, model_b_id)

        return {
            "arena_id": arena_id,
            "winner": winner,
            "model_a": {"id": model_a_id, "name": model_a.name if model_a else model_a_id},
            "model_b": {"id": model_b_id, "name": model_b.name if model_b else model_b_id},
            "revealed": True,
        }


benchmark_engine = BenchmarkEngine()
