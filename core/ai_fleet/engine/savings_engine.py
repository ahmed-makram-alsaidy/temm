"""Savings Engine & Financial Analytics for AI Fleet OS.
Calculates direct savings, avoided baseline costs, token heatmaps, budget thresholds,
subscription waste detection, and productivity ROI.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from ..storage.database import AsyncSessionLocal
from ..storage.models import TaskRun, ModelRecord, SubscriptionRecord, SystemSetting


class SavingsEngine:
    """Calculates financial intelligence, ROI, and smart savings for the AI Fleet."""

    async def get_savings_overview(self) -> Dict[str, Any]:
        """Aggregate total savings, spend, tokens, and ROI metrics."""
        async with AsyncSessionLocal() as session:
            # 1. Fetch runs
            runs_res = await session.execute(select(TaskRun).order_by(TaskRun.created_at.desc()))
            runs = runs_res.scalars().all()

            # 2. Fetch models for pricing calculations
            models_res = await session.execute(select(ModelRecord))
            models = {m.id: m for m in models_res.scalars().all()}

            # 3. Fetch budget & baseline settings
            settings_res = await session.execute(select(SystemSetting))
            settings = {s.key: s.value for s in settings_res.scalars().all()}

            # 4. Fetch subscriptions
            subs_res = await session.execute(select(SubscriptionRecord))
            subscriptions = subs_res.scalars().all()

        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = datetime(now.year, now.month, 1)

        total_actual_cost = 0.0
        total_reference_cost = 0.0
        total_saved_lifetime = 0.0

        today_actual_cost = 0.0
        today_saved = 0.0
        today_tokens = 0
        today_tasks_count = 0
        today_successful = 0

        week_saved = 0.0
        month_actual_cost = 0.0
        month_saved = 0.0
        month_tokens = 0

        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0

        # Breakdown buckets
        smart_routing_savings = 0.0
        free_models_savings = 0.0
        local_models_savings = 0.0
        cache_savings = 0.0

        tokens_by_category: Dict[str, int] = {}
        tokens_by_model: Dict[str, Dict[str, Any]] = {}

        for run in runs:
            total_actual_cost += run.actual_cost
            if run.status == "completed":
                total_reference_cost += run.reference_cost
                total_saved_lifetime += run.saved_amount

            total_input_tokens += run.input_tokens
            total_output_tokens += run.output_tokens
            total_cached_tokens += run.cached_tokens

            # Category distribution
            cat = run.task_type or "general"
            run_total_tokens = run.input_tokens + run.output_tokens
            tokens_by_category[cat] = tokens_by_category.get(cat, 0) + run_total_tokens

            # Model distribution
            m_id = run.selected_model_id or run.selected_agent_id or "unknown"
            if m_id not in tokens_by_model:
                m_name = models[m_id].name if m_id in models else m_id
                tokens_by_model[m_id] = {
                    "model_id": m_id,
                    "name": m_name,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "tasks_count": 0,
                }
            tokens_by_model[m_id]["input_tokens"] += run.input_tokens
            tokens_by_model[m_id]["output_tokens"] += run.output_tokens
            tokens_by_model[m_id]["cost"] += run.actual_cost
            tokens_by_model[m_id]["tasks_count"] += 1

            # Savings Breakdown attribution
            model = models.get(run.selected_model_id)
            if model and run.status == "completed":
                if model.is_local:
                    local_models_savings += run.saved_amount
                elif model.is_free:
                    free_models_savings += run.saved_amount
                else:
                    smart_routing_savings += run.saved_amount

            if run.cached_tokens > 0 and model:
                cache_savings += (run.cached_tokens / 1_000_000.0) * (model.input_cost_per_m - model.cache_cost_per_m)

            # Time-based filters
            if run.created_at:
                if run.created_at >= today_start:
                    today_actual_cost += run.actual_cost
                    today_saved += run.saved_amount if run.status == "completed" else 0.0
                    today_tokens += run_total_tokens
                    today_tasks_count += 1
                    if run.status == "completed":
                        today_successful += 1

                if run.created_at >= week_start:
                    week_saved += run.saved_amount if run.status == "completed" else 0.0

                if run.created_at >= month_start:
                    month_actual_cost += run.actual_cost
                    month_saved += run.saved_amount if run.status == "completed" else 0.0
                    month_tokens += run_total_tokens

        # Baseline & Budget calculations
        monthly_budget = float(settings.get("monthly_ai_budget", 100.0))
        budget_alert_threshold = float(settings.get("budget_alert_threshold", 80.0))
        budget_used_pct = (month_actual_cost / monthly_budget * 100.0) if monthly_budget > 0 else 0.0
        budget_remaining = max(0.0, monthly_budget - month_actual_cost)

        # Productivity ROI
        hourly_rate = float(settings.get("hourly_productivity_value", 25.0))
        # Estimate ~0.12 hours saved per completed AI task on average
        estimated_hours_saved = len([r for r in runs if r.status == 'completed']) * 0.15
        estimated_productivity_value = estimated_hours_saved * hourly_rate
        roi_multiplier = (estimated_productivity_value / max(total_actual_cost, 0.01))

        # Overall saving percentage
        overall_saving_pct = (
            (total_saved_lifetime / total_reference_cost * 100.0)
            if total_reference_cost > 0 else 0.0
        )

        return {
            "financials": {
                "today_saved": round(today_saved, 2),
                "week_saved": round(week_saved, 2),
                "month_saved": round(month_saved, 2),
                "lifetime_saved": round(total_saved_lifetime, 2),
                "today_spend": round(today_actual_cost, 4),
                "month_spend": round(month_actual_cost, 2),
                "reference_month_spend": round(month_actual_cost + month_saved, 2),
                "overall_saving_percentage": round(overall_saving_pct, 1),
                "monthly_budget": monthly_budget,
                "budget_used_percentage": round(budget_used_pct, 1),
                "budget_remaining": round(budget_remaining, 2),
                "budget_warning": budget_used_pct >= budget_alert_threshold,
                "budget_critical": budget_used_pct >= max(90.0, budget_alert_threshold + 10.0),
            },
            "savings_breakdown": {
                "smart_routing": round(smart_routing_savings, 2),
                "free_models": round(free_models_savings, 2),
                "local_models": round(local_models_savings, 2),
                "cache_savings": round(cache_savings, 2),
                "fallback_optimization": 0.0,
                "unused_premium_avoided": 0.0,
            },
            "tokens": {
                "today_total": today_tokens,
                "month_total": month_tokens,
                "lifetime_total": total_input_tokens + total_output_tokens,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cached_tokens": total_cached_tokens,
                "by_category": tokens_by_category,
                "by_model": list(tokens_by_model.values()),
            },
            "productivity_roi": {
                "hourly_rate": hourly_rate,
                "estimated_hours_saved": round(estimated_hours_saved, 1),
                "estimated_value_generated": round(estimated_productivity_value, 2),
                "total_ai_cost": round(total_actual_cost, 2),
                "roi_multiplier": round(roi_multiplier, 1),
            },
            "tasks_summary": {
                "total_today": today_tasks_count,
                "success_rate": round((today_successful / max(today_tasks_count, 1)) * 100.0, 1),
                "lifetime_tasks": len(runs),
            },
            "subscriptions": [s.to_dict() for s in subscriptions],
            "subscription_waste_advisor": self._generate_subscription_advice(subscriptions),
        }

    def _generate_subscription_advice(self, subscriptions: List[SubscriptionRecord]) -> List[Dict[str, Any]]:
        """Identify underused subscriptions and generate downgrade recommendations."""
        recommendations = []
        for sub in subscriptions:
            if sub.usage_percentage < 20.0:
                potential_saving = sub.monthly_cost * 0.9
                recommendations.append({
                    "subscription_id": sub.id,
                    "provider": sub.provider,
                    "plan_name": sub.plan_name,
                    "monthly_cost": sub.monthly_cost,
                    "usage_percentage": sub.usage_percentage,
                    "severity": "high" if sub.usage_percentage < 10.0 else "medium",
                    "action": "Cancel or Downgrade",
                    "reason": f"Only {sub.usage_percentage:.0f}% utilized this billing cycle ({sub.days_until_reset} days left).",
                    "monthly_potential_saving": potential_saving,
                })
        return recommendations


savings_engine = SavingsEngine()
