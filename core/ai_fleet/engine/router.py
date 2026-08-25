"""Smart Model Router & Escalation Engine for AI Fleet OS.
Analyzes task complexity, determines optimal routing mode, scores candidate models,
provides transparent reasoning, and manages automatic fallback chains.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from ..storage.database import AsyncSessionLocal
from ..storage.models import ModelRecord, SystemSetting


class ModelRouter:
    """Intelligent task router for matching tasks with the optimal model."""

    def classify_task(self, prompt: str) -> Dict[str, Any]:
        """Analyze prompt characteristics and determine task type and complexity."""
        p_lower = prompt.lower()

        # Detect Arabic
        arabic_chars = len(re.findall(r"[\u0600-\u06FF]", prompt))
        is_arabic = (arabic_chars / max(len(prompt), 1)) > 0.15 or bool(re.search(r"[\u0600-\u06FF]{3,}", prompt))

        # Detect Coding
        code_keywords = [
            "function", "def ", "class ", "import ", "const ", "async ", "await", "sql", "query",
            "api", "json", "jwt", "react", "flutter", "python", "typescript", "rust", "docker",
            "refactor", "bug", "stack trace", "regex", "git", "endpoint", "database", "orm"
        ]
        is_coding = any(k in p_lower for k in code_keywords) or bool(re.search(r"[{};()\[\]=><]{4,}", prompt))

        # Detect Deep Reasoning / Math
        reasoning_keywords = [
            "prove", "proof", "theorem", "calculate", "step-by-step", "architect", "consensus",
            "tradeoff", "analysis", "why does", "derive", "complexity", "bayes", "algorithm"
        ]
        is_reasoning = any(k in p_lower for k in reasoning_keywords)

        # Detect Fast / Brief
        fast_keywords = ["translate", "summarize", "rephrase", "bullet points", "quick", "tl;dr", "short"]
        is_fast = any(k in p_lower for k in fast_keywords) and len(prompt.split()) < 100

        # Primary Category
        if is_coding:
            primary_cat = "coding"
        elif is_reasoning:
            primary_cat = "reasoning"
        elif is_arabic:
            primary_cat = "arabic"
        elif is_fast:
            primary_cat = "fast"
        else:
            primary_cat = "general"

        # Complexity Estimate (1 - 5)
        length_factor = min(len(prompt.split()) / 150.0, 3.0)
        complexity = min(5, max(1, int(length_factor + (1.5 if is_coding or is_reasoning else 0.5))))

        return {
            "category": primary_cat,
            "complexity": complexity,
            "is_arabic": is_arabic,
            "is_coding": is_coding,
            "is_reasoning": is_reasoning,
            "word_count": len(prompt.split()),
            "estimated_input_tokens": int(len(prompt.split()) * 1.35),
        }

    async def recommend_model(
        self,
        prompt: str,
        mode: str = "balanced",  # economy, quality, balanced, fast, custom
        custom_weights: Optional[Dict[str, float]] = None,
        force_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate all active models and recommend the best model with full rationale.
        """
        task_info = self.classify_task(prompt)
        category = force_category or task_info["category"]

        async with AsyncSessionLocal() as session:
            # Fetch all active models
            res = await session.execute(select(ModelRecord).where(ModelRecord.is_active == True))
            models = res.scalars().all()

            # Fetch baseline reference model
            ref_res = await session.execute(
                select(SystemSetting.value).where(SystemSetting.key == "reference_baseline_model")
            )
            baseline_id = ref_res.scalar_one_or_none() or "gpt-4o"
            
            baseline_model = next((m for m in models if m.id == baseline_id), None)
            if not baseline_model and models:
                baseline_model = models[0]

        if not models:
            raise ValueError("No active models configured in the fleet registry.")

        # Score all models based on routing mode
        scored_candidates = []
        for model in models:
            score, explanation_parts = self._calculate_model_score(
                model=model,
                category=category,
                mode=mode,
                task_info=task_info,
                baseline_model=baseline_model,
                custom_weights=custom_weights,
            )
            scored_candidates.append({
                "model": model,
                "score": score,
                "explanation_parts": explanation_parts,
            })

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)

        winner_entry = scored_candidates[0]
        winner = winner_entry["model"]
        alternatives = scored_candidates[1:4]

        # Calculate estimated cost for winner vs baseline
        est_tokens_in = task_info["estimated_input_tokens"]
        est_tokens_out = max(250, int(est_tokens_in * 0.75))

        pricing_known = winner.pricing_provenance in {"verified", "provider_reported"} and baseline_model and baseline_model.pricing_provenance in {"verified", "provider_reported"}
        winner_est_cost = ((est_tokens_in / 1_000_000.0) * (winner.input_cost_per_m or 0) + (est_tokens_out / 1_000_000.0) * (winner.output_cost_per_m or 0)) if pricing_known else None
        baseline_est_cost = ((est_tokens_in / 1_000_000.0) * (baseline_model.input_cost_per_m or 0) + (est_tokens_out / 1_000_000.0) * (baseline_model.output_cost_per_m or 0)) if pricing_known else None
        est_saved = max(0.0, baseline_est_cost - winner_est_cost) if pricing_known else None
        saving_pct = (est_saved / baseline_est_cost * 100.0) if pricing_known and baseline_est_cost > 0 else None

        # Construct Transparent Reason String
        category_score = self._get_category_score(winner, category)
        reasons = [
            f"Category evidence: {category_score:.1f}/100" if category_score is not None else f"No verified {category} score is available.",
            f"{saving_pct:.1f}% estimated avoided cost vs {baseline_model.name}" if saving_pct is not None else "Pricing evidence is unavailable; no cost saving is claimed.",
            f"Measured/provider speed: {winner.tokens_per_sec:.0f} tokens/sec" if winner.tokens_per_sec is not None else "Speed evidence is unavailable.",
        ]
        if winner.is_free:
            reasons.append("Zero API cost (Free Tier / Local Model)")

        return {
            "selected_model": winner.to_dict(),
            "routing_mode": mode,
            "task_analysis": task_info,
            "score": round(winner_entry["score"], 1),
            "estimated_cost": round(winner_est_cost, 5) if winner_est_cost is not None else None,
            "reference_baseline_cost": round(baseline_est_cost, 5) if baseline_est_cost is not None else None,
            "estimated_saved": round(est_saved, 5) if est_saved is not None else None,
            "saving_percentage": round(saving_pct, 1) if saving_pct is not None else None,
            "reasons": reasons,
            "explanation": f"{winner.name} is the deterministic catalog candidate for {category}; quality, speed, and price claims remain unavailable until verified evidence exists.",
            "fallback_chain": [c["model"].id for c in scored_candidates[:4]],
            "alternatives": [
                {
                    "model": c["model"].to_dict(),
                    "score": round(c["score"], 1),
                    "estimated_cost": round(
                        (est_tokens_in / 1_000_000.0) * (c["model"].input_cost_per_m or 0) +
                        (est_tokens_out / 1_000_000.0) * (c["model"].output_cost_per_m or 0),
                        5
                    ) if c["model"].pricing_provenance in {"verified", "provider_reported"} else None,
                }
                for c in alternatives
            ],
        }

    def _get_category_score(self, model: ModelRecord, category: str) -> Optional[float]:
        if category == "coding":
            return model.coding_score
        elif category == "reasoning":
            return model.reasoning_score
        elif category == "arabic":
            return model.arabic_score
        elif category == "vision":
            return model.vision_score
        elif category == "fast":
            return model.speed_score
        return model.quality_score

    def _calculate_model_score(
        self,
        model: ModelRecord,
        category: str,
        mode: str,
        task_info: Dict[str, Any],
        baseline_model: Optional[ModelRecord],
        custom_weights: Optional[Dict[str, float]],
    ) -> Tuple[float, List[str]]:
        """Calculate weighted score for a candidate model based on mode."""
        cat_quality = self._get_category_score(model, category) or 0.0
        speed = model.speed_score or 0.0
        reliability = model.reliability_score or 0.0

        if model.pricing_provenance not in {"verified", "provider_reported"}:
            cost_efficiency = 0.0
        else:
            avg_cost = ((model.input_cost_per_m or 0) + (model.output_cost_per_m or 0)) / 2.0
            if model.is_free or model.is_local or avg_cost <= 0.0:
                cost_efficiency = 100.0
            else:
                cost_efficiency = max(10.0, 100.0 - (avg_cost * 7.5))

        if mode == "economy":
            # Economy mode strongly prioritizes free/cheap models that meet minimum quality
            if cat_quality < 75.0:
                score = cat_quality * 0.4
            else:
                score = (cost_efficiency * 0.65) + (cat_quality * 0.25) + (reliability * 0.10)
                if model.is_free or model.is_local:
                    score += 15.0  # Massive bonus for $0 cost

        elif mode == "quality":
            # Quality mode prioritizes capability & reasoning
            score = (cat_quality * 0.65) + (reliability * 0.20) + (speed * 0.10) + (cost_efficiency * 0.05)

        elif mode == "fast":
            # Fast mode prioritizes tokens/sec and low latency
            score = (speed * 0.55) + (cat_quality * 0.30) + (cost_efficiency * 0.15)

        elif mode == "custom" and custom_weights:
            w_q = custom_weights.get("quality", 0.40)
            w_c = custom_weights.get("cost", 0.30)
            w_s = custom_weights.get("speed", 0.20)
            w_r = custom_weights.get("reliability", 0.10)
            score = (cat_quality * w_q) + (cost_efficiency * w_c) + (speed * w_s) + (reliability * w_r)

        else:  # "balanced" (Default)
            score = (cat_quality * 0.40) + (cost_efficiency * 0.30) + (speed * 0.20) + (reliability * 0.10)

        return score, []


model_router = ModelRouter()
