"""Offline unit tests for the Gemini provider and ResearchAgent integration."""

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
    def __init__(self, api_key=None, response_text="Gemini test response"):
        self.api_key = api_key
        self.models = FakeModels(response_text=response_text)


def test_provider_requires_api_key(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_1"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="Gemini API key missing"):
        GeminiProvider()


def test_provider_prefers_canonical_environment_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "canonical")
    monkeypatch.setenv("GOOGLE_API_KEY", "fallback")
    provider = GeminiProvider(client=FakeGeminiClient())
    assert provider.api_key == "canonical"


def test_provider_uses_current_default_model(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    provider = GeminiProvider(
        api_key="test-key",
        client=FakeGeminiClient(),
    )
    assert provider.model == "gemini-3.8-flash"


def test_provider_generates_text(monkeypatch):
    client = FakeGeminiClient(response_text="A useful answer")
    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: client)
    provider = GeminiProvider(api_key="test-key", model="test-model")
    assert provider.generate_text("Explain CRM orchestration") == "A useful answer"
    assert client.models.calls == [{
        "model": "test-model",
        "contents": "Explain CRM orchestration",
    }]


def test_provider_rejects_empty_prompt(monkeypatch):
    monkeypatch.setattr(
        gemini_module.genai, "Client", lambda api_key: FakeGeminiClient()
    )
    provider = GeminiProvider(api_key="test-key")
    with pytest.raises(ValueError, match="non-empty string"):
        provider.generate_text("   ")


def test_provider_rejects_empty_model_response(monkeypatch):
    client = FakeGeminiClient(response_text="")
    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: client)
    provider = GeminiProvider(api_key="test-key")
    with pytest.raises(RuntimeError, match="returned no text"):
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
    result = agent.run({
        "question": "How can AI improve CRM operations?",
        "sources": ["Internal CRM SOP", "Campaign performance report"],
        "use_gemini": True,
    })

    assert result["status"] == "completed"
    assert result["engine"] == "Gemini"
    assert result["model"] == "test-model"
    assert result["report"].startswith("# Research report")
    assert result["source_count"] == 2
    assert len(provider.prompts) == 1
    assert "How can AI improve CRM operations?" in provider.prompts[0]
