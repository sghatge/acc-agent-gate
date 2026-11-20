from typing import Any

from opsforge.agents.base import BaseAgent
from opsforge.providers.gemini import GeminiProvider


class ResearchAgent(BaseAgent):
    """Gemini-powered OPSFORGE Research Agent."""

    name = "research"

    def __init__(self, provider=None):
        self.provider = provider

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Research task must be a dictionary.")

        question = task.get("question")
        sources = task.get("sources", [])

        if not isinstance(question, str) or not question.strip():
            raise ValueError("A non-empty research question is required.")

        if not isinstance(sources, list) or not sources:
            raise ValueError("At least one source is required.")

        if not all(isinstance(s, str) and s.strip() for s in sources):
            raise ValueError("Every source must be a non-empty string.")

        # Preserve the original flat response contract.
        if not task.get("use_gemini", False):
            return {
                "status": "draft",
                "question": question,
                "source_count": len(sources),
                "sources": sources,
                "message": (
                    "Research task validated. "
                    "Set use_gemini=True for AI execution."
                ),
            }

        provider = self.provider or GeminiProvider()

        prompt = f"""
You are the OPSFORGE Enterprise Research Agent.

Research question:
{question}

Provided source references:
{chr(10).join("- " + s for s in sources)}

Produce a professional Markdown report containing:
1. Executive summary
2. Key findings
3. Evidence gaps and assumptions
4. Risks
5. Recommendations
6. Suggested next steps

Do not invent citations, URLs, statistics or facts.
Clearly distinguish supplied references from verified evidence.
Disclose when source material has not been independently accessed.
"""

        try:
            report = provider.generate_text(prompt)
        except Exception as exc:
            raise RuntimeError(
                f"Gemini research execution failed: {exc}"
            ) from exc

        if not isinstance(report, str) or not report.strip():
            raise RuntimeError("Gemini returned an empty research report.")

        # Flat response: Orchestrator wraps this exactly once.
        return {
            "status": "completed",
            "question": question,
            "source_count": len(sources),
            "sources": sources,
            "report": report,
            "engine": "Gemini",
            "model": getattr(provider, "model", "configured Gemini model"),
        }
