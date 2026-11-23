"""Tests for the OPSFORGE CRM Operations Agent."""

import pytest

from opsforge.agents.crm_operations import CRMOperationsAgent


class FakeProvider:
    model = "test-model"

    def __init__(self, response="# CRM operations plan"):
        self.response = response
        self.prompts = []

    def generate_text(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_agent_registers_expected_name():
    assert CRMOperationsAgent().name == "crm_operations"


def test_agent_validates_task_type_and_objective():
    agent = CRMOperationsAgent()
    with pytest.raises(ValueError, match="dictionary"):
        agent.run("not a task")
    with pytest.raises(ValueError, match="objective"):
        agent.run({"objective": "  "})


def test_agent_validates_context_and_constraints():
    agent = CRMOperationsAgent()
    with pytest.raises(ValueError, match="Context"):
        agent.run({"objective": "Improve CRM", "context": 42})
    with pytest.raises(ValueError, match="Constraints"):
        agent.run({"objective": "Improve CRM", "constraints": "not a list"})
    with pytest.raises(ValueError, match="non-empty string"):
        agent.run({"objective": "Improve CRM", "constraints": ["  "]})


def test_agent_rejects_oversized_context():
    agent = CRMOperationsAgent()
    with pytest.raises(ValueError, match="20,000-character"):
        agent.run({"objective": "Improve CRM", "context": "x" * 20001})


def test_agent_returns_draft_without_gemini():
    result = CRMOperationsAgent().run({"objective": "Improve campaign QA"})
    assert result["status"] == "draft"
    assert result["agent"] == "crm_operations"


def test_agent_executes_with_injected_provider():
    provider = FakeProvider("# Prioritised CRM recommendations")
    agent = CRMOperationsAgent(provider=provider)

    result = agent.run({
        "objective": "Reduce campaign QA defects",
        "context": {
            "platform": "Adobe Campaign Classic",
            "known_issue": "Manual pre-send checks",
        },
        "constraints": ["No production changes", "Use existing team capacity"],
        "use_gemini": True,
    })

    assert result["status"] == "completed"
    assert result["engine"] == "Gemini"
    assert result["model"] == "test-model"
    assert result["execution_scope"] == "advisory_only"
    assert result["report"] == "# Prioritised CRM recommendations"
    assert len(provider.prompts) == 1
    assert "Reduce campaign QA defects" in provider.prompts[0]
    assert "Do not invent metrics" in provider.prompts[0]


def test_agent_rejects_empty_provider_response():
    provider = FakeProvider(" ")
    with pytest.raises(RuntimeError, match="empty CRM operations report"):
        CRMOperationsAgent(provider=provider).run({
            "objective": "Improve CRM operations",
            "use_gemini": True,
        })


def test_agent_wraps_provider_errors_without_exposing_exception_text():
    class BrokenProvider:
        model = "test-model"

        def generate_text(self, prompt):
            raise RuntimeError("sensitive provider details")

    with pytest.raises(RuntimeError, match="CRM operations analysis failed"):
        CRMOperationsAgent(provider=BrokenProvider()).run({
            "objective": "Improve CRM operations",
            "use_gemini": True,
        })
