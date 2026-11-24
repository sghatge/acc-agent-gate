"""Evidence-based campaign performance analytics for OPSFORGE."""

import json
import math
from typing import Any

from opsforge.agents.base import BaseAgent
from opsforge.providers.gemini import GeminiProvider


METRICS = ("sends", "delivered", "opens", "clicks", "conversions", "bounces", "revenue")


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Metric '{field}' must be a number.")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Metric '{field}' must be finite and non-negative.")
    return float(value)


def _aggregate(campaigns: list[dict[str, Any]]) -> dict[str, float]:
    totals = {metric: 0.0 for metric in METRICS}
    for campaign in campaigns:
        for metric in METRICS:
            totals[metric] += _number(campaign.get(metric, 0), metric)
    return totals


def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def _performance(totals: dict[str, float]) -> dict[str, Any]:
    return {
        **{key: round(value, 2) for key, value in totals.items()},
        "delivery_rate_pct": _rate(totals["delivered"], totals["sends"]),
        "bounce_rate_pct": _rate(totals["bounces"], totals["sends"]),
        "open_rate_pct": _rate(totals["opens"], totals["delivered"]),
        "click_through_rate_pct": _rate(totals["clicks"], totals["delivered"]),
        "click_to_open_rate_pct": _rate(totals["clicks"], totals["opens"]),
        "conversion_rate_pct": _rate(totals["conversions"], totals["clicks"]),
        "revenue_per_1000_sends": (
            round(totals["revenue"] / totals["sends"] * 1000, 2)
            if totals["sends"] else None
        ),
    }


class MarketingAnalyticsAgent(BaseAgent):
    """Calculate campaign KPIs and produce evidence-conscious insights."""

    def __init__(self, provider=None):
        super().__init__("marketing_analytics")
        self.provider = provider

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Marketing analytics task must be a dictionary.")

        campaigns = task.get("campaigns")
        if not isinstance(campaigns, list) or not campaigns:
            raise ValueError("At least one campaign record is required.")

        normalised = []
        seen = set()
        for index, campaign in enumerate(campaigns):
            if not isinstance(campaign, dict):
                raise ValueError(f"Campaign at index {index} must be a dictionary.")
            name = campaign.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Campaign at index {index} needs a non-empty name.")
            if name.strip() in seen:
                raise ValueError(f"Duplicate campaign name: {name.strip()}")
            seen.add(name.strip())
            record = {"name": name.strip()}
            for metric in METRICS:
                record[metric] = _number(campaign.get(metric, 0), metric)
            if record["delivered"] > record["sends"]:
                raise ValueError(f"Campaign '{name}' has delivered greater than sends.")
            if record["opens"] > record["delivered"]:
                raise ValueError(f"Campaign '{name}' has opens greater than delivered.")
            if record["clicks"] > record["delivered"]:
                raise ValueError(f"Campaign '{name}' has clicks greater than delivered.")
            if record["bounces"] > record["sends"]:
                raise ValueError(f"Campaign '{name}' has bounces greater than sends.")
            normalised.append(record)

        period = task.get("period", "unspecified")
        if not isinstance(period, str) or not period.strip():
            raise ValueError("Period must be a non-empty string.")

        threshold = _number(task.get("bounce_rate_threshold_pct", 1.5), "bounce_rate_threshold_pct")
        if threshold > 100:
            raise ValueError("bounce_rate_threshold_pct cannot exceed 100.")

        totals = _aggregate(normalised)
        overall = _performance(totals)
        campaign_results = []
        for record in normalised:
            stats = _performance({metric: record[metric] for metric in METRICS})
            campaign_results.append({"name": record["name"], **stats})

        insights = []
        bounce_rate = overall["bounce_rate_pct"]
        if bounce_rate is not None and bounce_rate > threshold:
            insights.append({
                "type": "deliverability_risk",
                "severity": "warning",
                "finding": f"Aggregate bounce rate is {bounce_rate}% versus the configured {threshold}% threshold.",
                "action": "Review hard/soft bounce composition, list hygiene, acquisition sources and sending-domain health.",
            })
        if overall["delivery_rate_pct"] is not None and overall["delivery_rate_pct"] < 98:
            insights.append({
                "type": "delivery_efficiency",
                "severity": "warning",
                "finding": f"Aggregate delivery rate is {overall['delivery_rate_pct']}%.",
                "action": "Segment delivery failures by ISP, domain, market and bounce class before changing sending strategy.",
            })

        zero_click = [item["name"] for item in campaign_results if item["delivered"] > 0 and item["clicks"] == 0]
        if zero_click:
            insights.append({
                "type": "engagement_gap",
                "severity": "warning",
                "finding": "Campaigns with delivered volume but no recorded clicks: " + ", ".join(zero_click),
                "action": "Validate tracking first, then review CTA visibility, offer relevance and audience intent.",
            })

        ranked = sorted(
            [item for item in campaign_results if item["click_through_rate_pct"] is not None],
            key=lambda item: (item["click_through_rate_pct"], item["conversions"]),
            reverse=True,
        )
        if ranked:
            insights.append({
                "type": "campaign_highlight",
                "severity": "info",
                "finding": f"Highest click-through rate: {ranked[0]['name']} ({ranked[0]['click_through_rate_pct']}%).",
                "action": "Inspect its audience, proposition and creative, then test transferable elements in comparable campaigns.",
            })

        comparison = None
        baseline = task.get("baseline_campaigns")
        if baseline is not None:
            if not isinstance(baseline, list) or not baseline:
                raise ValueError("baseline_campaigns must be a non-empty list when supplied.")
            baseline_totals = _aggregate(baseline)
            baseline_kpis = _performance(baseline_totals)
            deltas = {}
            for key in (
                "sends", "delivered", "opens", "clicks", "conversions", "revenue",
                "delivery_rate_pct", "bounce_rate_pct", "open_rate_pct",
                "click_through_rate_pct", "click_to_open_rate_pct", "conversion_rate_pct",
            ):
                current_value = overall[key]
                previous_value = baseline_kpis[key]
                if current_value is None or previous_value is None:
                    deltas[key] = None
                else:
                    deltas[key] = round(current_value - previous_value, 2)
            comparison = {"baseline": baseline_kpis, "absolute_deltas": deltas}

        result = {
            "status": "completed",
            "agent": self.name,
            "period": period.strip(),
            "campaign_count": len(normalised),
            "overall": overall,
            "campaigns": campaign_results,
            "rankings": {
                "by_click_through_rate": [item["name"] for item in ranked],
            },
            "insights": insights,
            "comparison": comparison,
            "metric_definitions": {
                "open_rate_pct": "opens / delivered * 100",
                "click_through_rate_pct": "clicks / delivered * 100",
                "click_to_open_rate_pct": "clicks / opens * 100",
                "conversion_rate_pct": "conversions / clicks * 100",
                "bounce_rate_pct": "bounces / sends * 100",
                "revenue_per_1000_sends": "revenue / sends * 1000",
            },
            "execution_scope": "analytics_advisory_only",
        }

        if task.get("use_gemini", False):
            provider = self.provider or GeminiProvider()
            prompt = f"""You are OPSFORGE's CRM Marketing Analytics Agent.
Interpret the calculated campaign performance data below.
All KPI calculations are deterministic and must be preserved exactly.
Do not invent benchmarks, causal explanations, attribution, missing values or business outcomes.
Separate observed facts from hypotheses. Mention sample-size and tracking limitations where relevant.
Prioritise recommendations by impact, effort and validation dependency.
Provide: executive summary, KPI interpretation, strongest/weakest signals,
likely hypotheses clearly labelled, recommended experiments, and next-step measurement plan.
Calculated evidence (JSON):
{json.dumps(result, ensure_ascii=False, default=str)}
"""
            try:
                report = provider.generate_text(prompt)
            except Exception as exc:
                raise RuntimeError(
                    f"Marketing analytics narrative failed: {type(exc).__name__}"
                ) from exc
            if not isinstance(report, str) or not report.strip():
                raise RuntimeError("Gemini returned an empty marketing analytics report.")
            result["narrative"] = report
            result["engine"] = "Gemini"
            result["model"] = getattr(provider, "model", "configured Gemini model")

        return result
