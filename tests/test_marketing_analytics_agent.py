"""Tests for the OPSFORGE Marketing Analytics Agent."""

import pytest

from opsforge.agents.marketing_analytics import MarketingAnalyticsAgent


def sample_campaigns():
    return [
        {
            "name": "Flagship launch",
            "sends": 10000, "delivered": 9800, "opens": 4900,
            "clicks": 980, "conversions": 98, "bounces": 200,
            "revenue": 250000,
        },
        {
            "name": "Triggered cross-sell",
            "sends": 5000, "delivered": 4950, "opens": 2970,
            "clicks": 990, "conversions": 150, "bounces": 50,
            "revenue": 180000,
        },
    ]


def test_agent_calculates_aggregate_kpis():
    result = MarketingAnalyticsAgent().run({
        "period": "Jan-Aug 2026",
        "campaigns": sample_campaigns(),
    })
    overall = result["overall"]
    assert result["campaign_count"] == 2
    assert overall["sends"] == 15000
    assert overall["delivered"] == 14750
    assert overall["delivery_rate_pct"] == 98.33
    assert overall["bounce_rate_pct"] == 1.67
    assert overall["open_rate_pct"] == 53.42
    assert overall["click_through_rate_pct"] == 13.36
    assert overall["conversion_rate_pct"] == 12.17
    assert result["execution_scope"] == "analytics_advisory_only"


def test_agent_flags_bounce_rate_above_configured_threshold():
    result = MarketingAnalyticsAgent().run({"campaigns": sample_campaigns()})
    finding = next(i for i in result["insights"] if i["type"] == "deliverability_risk")
    assert "1.5%" in finding["finding"]


def test_agent_ranks_campaigns_by_ctr():
    result = MarketingAnalyticsAgent().run({"campaigns": sample_campaigns()})
    assert result["rankings"]["by_click_through_rate"][0] == "Triggered cross-sell"


def test_agent_compares_baseline_period():
    baseline = [{
        "name": "Previous period",
        "sends": 10000, "delivered": 9700, "opens": 4000,
        "clicks": 700, "conversions": 70, "bounces": 300,
        "revenue": 150000,
    }]
    result = MarketingAnalyticsAgent().run({
        "campaigns": sample_campaigns(),
        "baseline_campaigns": baseline,
    })
    assert result["comparison"]["absolute_deltas"]["clicks"] == 1270.0
    assert result["comparison"]["absolute_deltas"]["bounce_rate_pct"] == -1.33


def test_agent_handles_zero_denominators():
    result = MarketingAnalyticsAgent().run({
        "campaigns": [{
            "name": "Empty delivery", "sends": 0, "delivered": 0,
            "opens": 0, "clicks": 0, "conversions": 0, "bounces": 0,
        }]
    })
    assert result["overall"]["open_rate_pct"] is None
    assert result["overall"]["revenue_per_1000_sends"] is None


@pytest.mark.parametrize(
    "task, message",
    [
        ({"campaigns": []}, "At least one campaign"),
        ({"campaigns": ["not a record"]}, "must be a dictionary"),
        ({"campaigns": [{"sends": 10}]}, "non-empty name"),
        ({"campaigns": [{"name": "A", "sends": -1}]}, "non-negative"),
        ({"campaigns": [{"name": "A", "sends": float("nan")}]}, "finite"),
        ({"campaigns": [{"name": "A", "delivered": 2, "sends": 1}]}, "delivered greater than sends"),
        ({"campaigns": [{"name": "A"}, {"name": "A"}]}, "Duplicate campaign"),
    ],
)
def test_agent_rejects_invalid_input(task, message):
    with pytest.raises(ValueError, match=message):
        MarketingAnalyticsAgent().run(task)


def test_agent_validates_period_and_threshold():
    with pytest.raises(ValueError, match="Period"):
        MarketingAnalyticsAgent().run({
            "period": " ", "campaigns": sample_campaigns()
        })
    with pytest.raises(ValueError, match="cannot exceed 100"):
        MarketingAnalyticsAgent().run({
            "campaigns": sample_campaigns(),
            "bounce_rate_threshold_pct": 101,
        })


def test_agent_adds_gemini_narrative_without_changing_calculations():
    class FakeProvider:
        model = "test-model"

        def generate_text(self, prompt):
            assert "must be preserved exactly" in prompt
            return "Prioritise the triggered cross-sell journey."

    result = MarketingAnalyticsAgent(provider=FakeProvider()).run({
        "campaigns": sample_campaigns(),
        "use_gemini": True,
    })
    assert result["overall"]["clicks"] == 1970
    assert result["narrative"].startswith("Prioritise")
    assert result["engine"] == "Gemini"


def test_agent_integrates_with_registry_and_orchestrator():
    from opsforge.agents.registry import AgentRegistry
    from opsforge.orchestrator import Orchestrator

    registry = AgentRegistry()
    registry.register(MarketingAnalyticsAgent())
    result = Orchestrator(registry).execute(
        "marketing_analytics",
        {"campaigns": sample_campaigns()},
    )
    assert result["status"] == "completed"
    assert result["result"]["overall"]["sends"] == 15000
