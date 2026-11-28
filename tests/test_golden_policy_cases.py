"""Golden policy contract tests for representative ACC Agent Gate decisions.

These cases are synthetic regression fixtures. They do not connect to Adobe Campaign.
"""
import json
from pathlib import Path

import pytest

from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy


CASES = json.loads(
    (Path(__file__).parent / "golden_policy_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_golden_policy_decision(case):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())

    result = gate.call(case["tool"], case["args"])

    assert result["decision"]["decision"] == case["expected_decision"], (
        f"Golden case {case['id']} expected {case['expected_decision']}, "
        f"received {result['decision']['decision']}: {result['decision']}"
    )
    if case["id"] == "qa-passed-send-still-needs-human-approval":
        assert result["decision"]["approvals_required"] == 1
        assert result["result"]["ticket"]
    if case["id"] == "send-with-qa-blocker-is-blocked":
        assert gate.backend.deliveries["DM_BF26_SI"].state == "ready"
