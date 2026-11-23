from typing import Any

from opsforge.agents.registry import AgentRegistry


class Orchestrator:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def execute(
        self,
        agent_name: str,
        task: dict[str, Any]
    ) -> dict[str, Any]:

        agent = self.registry.get(agent_name)
        result = agent.run(task)

        return {
            "agent": agent_name,
            "status": "completed",
            "result": result,
        }
