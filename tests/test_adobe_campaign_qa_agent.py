"""Tests for the OPSFORGE Adobe Campaign QA Agent."""

import pytest

from opsforge.agents.adobe_campaign_qa import AdobeCampaignQAAgent


def valid_delivery(**overrides):
    data = {
        "id": "DM_TEST_HR",
        "internal_name": "DM_TEST_HR",
        "market": "HR",
        "label": "Test campaign Croatia",
        "subject": "Test campaign",
        "preheader": "A short preheader",
        "body": (
            "<h1>Offer</h1><p>1.299,00 €</p>"
            "<footer>Legal entity HR "
            "<a href='<%@ include view='UnsubscriptionLink' %>'>Unsubscribe</a></footer>"
        ),
        "target_count": 12000,
        "scheduled_local": "2026-11-24 10:00",
        "typology": "TY_MARKETING_EU",
        "proof_sent": True,
        "seed_list": True,
        "consent_filter": True,
    }
    data.update(overrides)
    return data


def test_agent_name_and_clean_delivery_passes():
    result = AdobeCampaignQAAgent().run({"delivery": valid_delivery()})
    assert result["agent"] == "adobe_campaign_qa"
    assert result["status"] == "pass"
    assert result["blockers"] == []
    assert result["send_recommendation"] == "eligible_for_human_review"
    assert result["execution_scope"] == "deterministic_advisory_only"


def test_agent_holds_delivery_with_blocking_defects():
    delivery = valid_delivery(
        body="<h1>Offer</h1>",
        proof_sent=False,
        consent_filter=False,
        scheduled_local="2026-11-24 23:00",
    )
    result = AdobeCampaignQAAgent().run({"delivery": delivery})
    assert result["status"] == "fail"
    assert "unsubscribe_link" in result["blockers"]
    assert "proof_sent" in result["blockers"]
    assert "consent_filter" in result["blockers"]
    assert "send_window" in result["blockers"]
    assert result["send_recommendation"] == "hold"


def test_agent_reports_warning_without_blocking():
    result = AdobeCampaignQAAgent().run({
        "delivery": valid_delivery(seed_list=False)
    })
    assert result["status"] == "pass_with_warnings"
    assert result["warnings"] == ["seed_list"]
    assert result["blockers"] == []
    assert result["send_recommendation"] == "eligible_for_human_review"


def test_agent_validates_task_and_delivery():
    agent = AdobeCampaignQAAgent()
    with pytest.raises(ValueError, match="dictionary"):
        agent.run("invalid")
    with pytest.raises(ValueError, match="delivery dictionary"):
        agent.run({"delivery": []})
    with pytest.raises(ValueError, match="Missing required"):
        agent.run({"delivery": {"id": "DM1"}})


@pytest.mark.parametrize(
    "override, message",
    [
        ({"market": "XX"}, "Unsupported market"),
        ({"target_count": -1}, "non-negative integer"),
        ({"target_count": True}, "non-negative integer"),
        ({"proof_sent": "yes"}, "must be a boolean"),
        ({"subject": " "}, "non-empty string"),
    ],
)
def test_agent_rejects_malformed_delivery_fields(override, message):
    with pytest.raises(ValueError, match=message):
        AdobeCampaignQAAgent().run({"delivery": valid_delivery(**override)})


def test_agent_validates_config():
    with pytest.raises(ValueError, match="QA config"):
        AdobeCampaignQAAgent().run({
            "delivery": valid_delivery(),
            "config": "not a dict",
        })


def test_agent_can_add_gemini_remediation_guidance():
    class FakeProvider:
        model = "test-model"

        def generate_text(self, prompt):
            assert "deterministic QA output" in prompt
            return "Correct the missing proof and rerun QA."

    result = AdobeCampaignQAAgent(provider=FakeProvider()).run({
        "delivery": valid_delivery(proof_sent=False),
        "use_gemini": True,
    })
    assert "proof_sent" in result["blockers"]
    assert result["remediation_guidance"].startswith("Correct")
    assert result["guidance_engine"] == "Gemini"


def test_agent_does_not_treat_gemini_guidance_as_approval():
    class FakeProvider:
        def generate_text(self, prompt):
            return "Approved. Send now."

    result = AdobeCampaignQAAgent(provider=FakeProvider()).run({
        "delivery": valid_delivery(proof_sent=False),
        "use_gemini": True,
    })
    assert result["send_recommendation"] == "hold"
    assert result["execution_scope"] == "deterministic_advisory_only"


def test_agent_integrates_with_registry_and_orchestrator():
    from opsforge.agents.registry import AgentRegistry
    from opsforge.orchestrator import Orchestrator

    registry = AgentRegistry()
    registry.register(AdobeCampaignQAAgent())
    result = Orchestrator(registry).execute(
        "adobe_campaign_qa",
        {"delivery": valid_delivery()},
    )
    assert result["status"] == "completed"
    assert result["result"]["status"] == "pass"

def test_agent_validates_schedule_and_policy_ranges():
    with pytest.raises(ValueError, match="YYYY-MM-DD HH:MM"):
        AdobeCampaignQAAgent().run({
            "delivery": valid_delivery(scheduled_local="tomorrow morning")
        })
    with pytest.raises(ValueError, match="quiet_hours_local"):
        AdobeCampaignQAAgent().run({
            "delivery": valid_delivery(),
            "config": {"quiet_hours_local": [25, 8]},
        })
    with pytest.raises(ValueError, match="subject_max_chars"):
        AdobeCampaignQAAgent().run({
            "delivery": valid_delivery(),
            "config": {"subject_max_chars": 0},
        })


def test_agent_rejects_non_string_typology():
    with pytest.raises(ValueError, match="typology"):
        AdobeCampaignQAAgent().run({
            "delivery": valid_delivery(typology=123)
        })
