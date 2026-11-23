from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a task and return a structured result."""
        raise NotImplementedError
