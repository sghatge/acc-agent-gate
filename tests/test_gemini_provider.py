"""Unit tests for the Gemini provider and ResearchAgent integration.

All tests use a fake Gemini client/provider; no live API key or network access
is required.
"""

import pytest

from opsforge.agents.research import ResearchAgent
from opsforge.providers import gemini as gemini_module
from opsforge.providers.gemini import GeminiProvider


class FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, response_text="Gemini test response"):
        self.response_text = response_text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return FakeGeminiResponse(self.response_text)


class FakeGeminiClient:
    def __init__(self, api_key, response_text="Gemini test response"):
        self.api_key = api_key
        self.models = FakeModels(response_text=response_text)


def test_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_1", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider()


def test_provider_uses_configured_key_and_model(monkeypatch):
    clients = []

    def fake_client(api_key):
        client = FakeGeminiClient(api_key)
        clients.append(client)
        return client

    monkeypatch.setattr(gemini_module.genai, "Client", fake_client)
    provider = GeminiProvider(api_key="test-key", model="test-model")

    assert provider.api_key == "test-key"
    assert provider.model == "test-model"
    assert clients[0].api_key == "test-key"


def test_provider_generates_text(monkeypatch):
    client = FakeGeminiClient(response_text="A useful answer")
    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: client)
    provider = GeminiProvider(api_key="test-key", model="test-model")

    result = provider.generate_text("Explain CRM orchestration")

    assert result == "A useful answer"
    assert client.models.calls == [
        {
            "model": "test-model",
            "contents": "Explain CRM orchestration",
        }
    ]


def test_provider_rejects_empty_prompt(monkeypatch):
    monkeypatch.setattr(
        gemini_module.genai, "Client", lambda api_key: FakeGeminiClient(api_key)
    )
    provider = GeminiProvider(api_key="test-key")

    with pytest.raises(ValueError, match="Prompt cannot be empty"):
        provider.generate_text("   ")


def test_provider_rejects_empty_model_response(monkeypatch):
    client = FakeGeminiClient(response_text="")
    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: client)
    provider = GeminiProvider(api_key="test-key")

    with pytest.raises(RuntimeError, match="empty response"):
        provider.generate_text("Run a test prompt")


def test_research_agent_executes_through_injected_provider():
    class FakeProvider:
        model = "test-model"

        def __init__(self):
            self.prompts = []

        def generate_text(self, prompt):
            self.prompts.append(prompt)
            return "# Research report\\n\\nTest findings."

    provider = FakeProvider()
    agent = ResearchAgent(provider=provider)

    result = agent.run(
        {
            "question": "How can AI improve CRM operations?",
            "sources": ["Internal CRM SOP", "Campaign performance report"],
            "use_gemini": True,
        }
    )

    assert result["status"] == "completed"
    assert result["engine"] == "Gemini"
    assert result["model"] == "test-model"
    assert result["report"].startswith("# Research report")
    assert result["source_count"] == 2
    assert len(provider.prompts) == 1
    assert "How can AI improve CRM operations?" in provider.prompts[0]
