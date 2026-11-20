from .base import BaseAgent


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            raise ValueError(
                f"Agent already registered: {agent.name}"
            )
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        if name not in self._agents:
            raise KeyError(f"Unknown agent: {name}")
        return self._agents[name]

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())
