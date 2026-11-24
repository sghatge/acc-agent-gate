import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "streamlit_app.py"


def test_streamlit_app_is_valid_python_and_uses_governed_components():
    source = APP.read_text(encoding="utf-8")
    ast.parse(source)
    assert "PersistentApprovalStore" in source
    assert "ExecutionAuthorizer" in source
    assert "MockCampaignInstance" in source
    assert "AuditLog.verify" in source
    assert "No MCP tool or AI agent can issue or consume execution permits." in source


def test_streamlit_app_declares_synthetic_only_and_advisory_gemini_boundary():
    source = APP.read_text(encoding="utf-8")
    assert "SYNTHETIC DEMO ONLY" in source
    assert "It cannot connect to or send through a real Adobe Campaign instance." in source
    assert "The deterministic policy engine is authoritative; you are not a decision-maker." in source
