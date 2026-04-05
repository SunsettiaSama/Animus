from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAction(ABC):
    name: str

    @abstractmethod
    def execute(self, **kwargs) -> str:
        raise NotImplementedError
