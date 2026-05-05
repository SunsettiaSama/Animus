from __future__ import annotations

from infra.base_service import BaseServiceManager


class ServiceRegistry:
    """Central registry of all managed infrastructure services.

    Services are registered by name and expose a uniform interface via
    ``BaseServiceManager``.  The registry is used by the WebUI to power
    ``/api/services/*`` endpoints and by the ``_shutdown`` handler to stop
    all services gracefully in one call.

    Usage::

        registry = ServiceRegistry()
        registry.register("vllm",    vllm_manager)
        registry.register("searxng", searxng_manager)

        registry.status_all()   # → {"vllm": {...}, "searxng": {...}}
        registry.stop_all()     # graceful shutdown of every registered service
    """

    def __init__(self) -> None:
        self._services: dict[str, BaseServiceManager] = {}

    def register(self, name: str, mgr: BaseServiceManager) -> None:
        self._services[name] = mgr

    def get(self, name: str) -> BaseServiceManager | None:
        return self._services.get(name)

    def names(self) -> list[str]:
        return list(self._services.keys())

    def status_all(self) -> dict[str, dict]:
        return {name: mgr.status() for name, mgr in self._services.items()}

    def stop_all(self) -> None:
        for mgr in self._services.values():
            mgr.stop()
