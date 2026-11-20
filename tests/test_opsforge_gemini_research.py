from unittest.mock import Mock

import pytest

from opsforge.agents.research import ResearchAgent


def test_legacy_validation_mode():
    agent = ResearchAgent()
    result = agent.run({
        "question": "Assess enterprise AI governance",
        "sources": ["Internal architecture document"],
    })

    assert result["status"] == "draft"
    assert result["source_count"] == 1


def test_gemini_research_execution():
    provider = Mock()
    provider.model = "test-model"
    provider.generate_text.return_value = "# Research report"

    agent = ResearchAgent(provider=provider)
    result = agent.run({
        "question": "Assess enterprise AI governance",
        "sources": ["Architecture document"],
        "use_gemini": True,
    })

    assert result["status"] == "completed"
    assert result["engine"] == "Gemini"
    assert result["report"] == "# Research report"
    provider.generate_text.assert_called_once()


def test_missing_question_rejected():
    agent = ResearchAgent()

    with pytest.raises(ValueError):
        agent.run({"sources": ["Document"]})


def test_missing_sources_rejected():
    agent = ResearchAgent()

    with pytest.raises(ValueError):
        agent.run({"question": "Research AI governance", "sources": []})


def test_gemini_failure_propagated():
    provider = Mock()
    provider.generate_text.side_effect = RuntimeError("API unavailable")

    agent = ResearchAgent(provider=provider)

    with pytest.raises(RuntimeError, match="Gemini research execution failed"):
        agent.run({
            "question": "Research AI governance",
            "sources": ["Document"],
            "use_gemini": True,
        })
