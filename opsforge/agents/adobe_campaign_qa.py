"""Deterministic Adobe Campaign pre-send QA agent for OPSFORGE."""

from typing import Any

from acc_agent_gate.mock_instance import Delivery, MARKETS
from acc_agent_gate.qa import run_qa
from opsforge.agents.base import BaseAgent
from opsforge.providers.gemini import GeminiProvider


class AdobeCampaignQAAgent(BaseAgent):
    """Run deterministic pre-send checks against supplied delivery evidence.

    The agent reuses ACC Agent Gate's QA rules. It never connects to an
    Adobe Campaign instance and never sends, edits, or approves a delivery.
    """

    REQUIRED_FIELDS = (
        "id", "internal_name", "market", "label", "subject",
        "preheader", "body", "target_count", "scheduled_local",
    )

    def __init__(self, provider=None):
        super().__init__("adobe_campaign_qa")
        self.provider = provider

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Adobe Campaign QA task must be a dictionary.")

        delivery_data = task.get("delivery")
        if not isinstance(delivery_data, dict):
            raise ValueError("A delivery dictionary is required.")

        missing = [key for key in self.REQUIRED_FIELDS if key not in delivery_data]
        if missing:
            raise ValueError("Missing required delivery fields: " + ", ".join(missing))

        for key in ("id", "internal_name", "market", "label", "subject",
                    "preheader", "body", "scheduled_local"):
            if not isinstance(delivery_data[key], str) or not delivery_data[key].strip():
                raise ValueError(f"Delivery field '{key}' must be a non-empty string.")

        market = delivery_data["market"].upper()
        if market not in MARKETS:
            raise ValueError(f"Unsupported market '{market}'. Supported markets: {', '.join(sorted(MARKETS))}.")

        if isinstance(delivery_data["target_count"], bool) or not isinstance(delivery_data["target_count"], int) or delivery_data["target_count"] < 0:
            raise ValueError("target_count must be a non-negative integer.")

        for key in ("proof_sent", "seed_list", "consent_filter"):
            if key in delivery_data and not isinstance(delivery_data[key], bool):
                raise ValueError(f"Delivery field '{key}' must be a boolean.")

        config = task.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("QA config must be a dictionary.")

        delivery = Delivery(
            id=delivery_data["id"].strip(),
            internal_name=delivery_data["internal_name"].strip(),
            market=market,
            label=delivery_data["label"].strip(),
            subject=delivery_data["subject"],
            preheader=delivery_data["preheader"],
            body=delivery_data["body"],
            target_count=delivery_data["target_count"],
            scheduled_local=delivery_data["scheduled_local"].strip(),
            typology=delivery_data.get("typology", "TY_MARKETING_EU"),
            proof_sent=delivery_data.get("proof_sent", False),
            seed_list=delivery_data.get("seed_list", False),
            consent_filter=delivery_data.get("consent_filter", False),
        )

        qa_result = run_qa(delivery, config)
        result = {
            "status": qa_result["status"],
            "agent": self.name,
            "delivery": qa_result["delivery"],
            "market": qa_result["market"],
            "passed": qa_result["passed"],
            "total": qa_result["total"],
            "blockers": qa_result["blockers"],
            "warnings": qa_result["warnings"],
            "checks": qa_result["checks"],
            "send_recommendation": "hold" if qa_result["blockers"] else "eligible_for_human_review",
            "execution_scope": "deterministic_advisory_only",
        }

        if task.get("use_gemini", False):
            provider = self.provider or GeminiProvider()
            prompt = f"""You are an Adobe Campaign Classic pre-send QA remediation assistant.
Review this deterministic QA output and provide concise, prioritised remediation guidance.
Do not change any check result, invent evidence, approve a send, or claim to access Campaign.
A blocker means the delivery must remain on hold until the defect is corrected and QA is rerun.
QA evidence (JSON):
{result}
Return: release assessment, blocker-by-blocker fix guidance, warning handling,
evidence required for re-test, and a short human sign-off checklist."""
            try:
                guidance = provider.generate_text(prompt)
            except Exception as exc:
                raise RuntimeError(
                    f"Adobe Campaign QA guidance failed: {type(exc).__name__}"
                ) from exc
            if not isinstance(guidance, str) or not guidance.strip():
                raise RuntimeError("Gemini returned empty Adobe Campaign QA guidance.")
            result["remediation_guidance"] = guidance
            result["guidance_engine"] = "Gemini"

        return result
