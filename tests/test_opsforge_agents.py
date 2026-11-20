
import pytest

from opsforge.agents.base import BaseAgent
from opsforge.agents.registry import AgentRegistry
from opsforge.agents.research import ResearchAgent
from opsforge.orchestrator import Orchestrator


def test_research_agent_initialization():
    agent = ResearchAgent()
    assert agent.name == "research"


def test_research_agent_returns_structured_result():
    agent = ResearchAgent()

    result = agent.run({
        "question": "How can AI improve CRM operations?",
        "sources": ["Source A", "Source B"],
    })

    assert result["question"] == "How can AI improve CRM operations?"
    assert result["source_count"] == 2
    assert result["status"] == "draft"


def test_research_agent_rejects_empty_question():
    agent = ResearchAgent()

    with pytest.raises(ValueError):
        agent.run({
            "question": "",
            "sources": ["Source A"],
        })


def test_research_agent_rejects_empty_sources():
    agent = ResearchAgent()

    with pytest.raises(ValueError):
        agent.run({
            "question": "Test question",
            "sources": [],
        })


def test_registry_registers_and_retrieves_agent():
    registry = AgentRegistry()
    agent = ResearchAgent()

    registry.register(agent)

    assert registry.get("research") is agent
    assert registry.list_agents() == ["research"]


def test_registry_rejects_duplicate_agents():
    registry = AgentRegistry()

    registry.register(ResearchAgent())

    with pytest.raises(ValueError):
        registry.register(ResearchAgent())


def test_registry_rejects_unknown_agent():
    registry = AgentRegistry()

    with pytest.raises(KeyError):
        registry.get("unknown")


def test_orchestrator_executes_research_agent():
    registry = AgentRegistry()
    registry.register(ResearchAgent())

    orchestrator = Orchestrator(registry)

    result = orchestrator.execute(
        "research",
        {
            "question": "Test CRM research",
            "sources": ["Source A"],
        },
    )

    assert result["agent"] == "research"
    assert result["status"] == "completed"
    assert result["result"]["source_count"] == 1

