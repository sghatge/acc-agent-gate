"""ACC Agent Gate – a governance layer between AI agents and Adobe Campaign."""
from .audit import AuditLog
from .gate import AgentGate, Decision, load_policy
from .mock_instance import MockCampaignInstance
from .qa import run_qa

__all__ = ["AgentGate", "AuditLog", "Decision", "MockCampaignInstance", "load_policy", "run_qa"]
__version__ = "0.1.0"
