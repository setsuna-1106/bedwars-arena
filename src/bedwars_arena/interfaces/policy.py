"""Minimal in-process policy interface; policies never receive WorldState."""
from typing import Protocol


class Policy(Protocol):
    name: str
    version: str

    def act(self, observation: dict) -> list[dict]:
        """Return request objects for the observed player and round."""
        ...
