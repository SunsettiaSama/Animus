from __future__ import annotations

from abc import ABC, abstractmethod


class BaseServiceManager(ABC):
    """Abstract base for all infrastructure service managers.

    Each concrete subclass manages the lifecycle of one external service
    (subprocess, Docker container, etc.) and exposes a uniform interface
    consumed by ``ServiceRegistry`` and the ``/api/services/*`` endpoints.

    Subclasses must implement ``start``, ``stop``, and ``status``.
    ``status()`` must always return a dict containing at least a ``"state"``
    key whose value is one of: ``"stopped"``, ``"starting"``, ``"running"``,
    ``"error"``.
    """

    @abstractmethod
    def start(self, **kwargs) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict:
        raise NotImplementedError

    def get_logs(self, n: int = 100) -> list[str]:
        return []
