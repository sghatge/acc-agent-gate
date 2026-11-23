"""Gemini-powered CRM operations advisory agent for OPSFORGE."""

import json
from typing import Any

from opsforge.agents.base import BaseAgent
from opsforge.providers.gemini import GeminiProvider


class CRMOperationsAgent(BaseAgent):
    """Turn supplied CRM operating context into an actionable advisory plan.

    The agent analyses only the information supplied in the task. It does not
    connect to CRM platforms, execute campaigns, or independently verify data.
    """

    def __init__(self, provider=None):
        super().__init__("crm_operations")
        self.provider = provider

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("CRM operations task must be a dictionary.")

        objective = task.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("A non-empty objective is required.")

        context = task.get("context", {})
        if not isinstance(context, (dict, str)):
            raise ValueError("Context must be a dictionary or string.")

        constraints = task.get("constraints", [])
        if not isinstance(constraints, list):
            raise ValueError("Constraints must be a list of strings.")
        if not all(isinstance(item, str) and item.strip() for item in constraints):
            raise ValueError("Every constraint must be a non-empty string.")

        context_text = (
            json.dumps(context, indent=2, ensure_ascii=False, default=str)
            if isinstance(context, dict)
            else context.strip()
        )
        if len(context_text) > 20000:
            raise ValueError("Context exceeds the 20,000-character task limit.")

        if not task.get("use_gemini", False):
            return {
                "status": "draft",
                "agent": self.name,
                "objective": objective.strip(),
                "message": "CRM operations task validated. Set use_gemini=True for AI execution.",
            }

        provider = self.provider or GeminiProvider()
        prompt = f"""
You are OPSFORGE's enterprise CRM Operations Agent.

OBJECTIVE
{objective.strip()}

SUPPLIED OPERATING CONTEXT
{context_text or "No additional context supplied."}

CONSTRAINTS
{chr(10).join("- " + item for item in constraints) or "- No explicit constraints supplied."}

Prepare a practical, evidence-conscious CRM operations advisory in Markdown.
Use these sections:
1. Executive summary
2. Current-state assessment
3. Operational opportunities and root causes
4. Prioritised recommendations (impact, effort, dependency)
5. 30/60/90-day implementation roadmap
6. KPIs and measurement approach
7. Risks, controls and governance
8. Assumptions and missing evidence

Rules:
- Treat supplied context as unverified input, not independently validated fact.
- Do not invent metrics, baselines, system capabilities, integrations or outcomes.
- Label assumptions and propose how to validate them.
- Distinguish recommendations from actions actually executed.
- Do not claim to access or modify any CRM platform.
- Prefer measurable recommendations with owners/roles and dependencies where feasible.
"""
        try:
            report = provider.generate_text(prompt)
        except Exception as exc:
            raise RuntimeError(
                f"CRM operations analysis failed: {type(exc).__name__}"
            ) from exc

        if not isinstance(report, str) or not report.strip():
            raise RuntimeError("Gemini returned an empty CRM operations report.")

        return {
            "status": "completed",
            "agent": self.name,
            "objective": objective.strip(),
            "report": report,
            "engine": "Gemini",
            "model": getattr(provider, "model", "configured Gemini model"),
            "execution_scope": "advisory_only",
        }
