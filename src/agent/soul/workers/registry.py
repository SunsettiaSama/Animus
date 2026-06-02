from __future__ import annotations

from typing import Any

from .domain_worker import DomainWorker


class SoulWorkers:
    """Soul 域 worker 注册表，由 SoulService 统一 start/stop/status。"""

    def __init__(
        self,
        *,
        memory: DomainWorker | None = None,
        persona: DomainWorker | None = None,
        life: DomainWorker | None = None,
        presence: DomainWorker | None = None,
        story: DomainWorker | None = None,
    ) -> None:
        self.memory = memory or DomainWorker("memory-worker")
        self.persona = persona or DomainWorker("persona-worker")
        self.presence = presence or DomainWorker("presence-worker")
        self.life: DomainWorker | None = life
        self.story: DomainWorker | None = story

    def register_life(self, worker: DomainWorker) -> None:
        self.life = worker

    def register_story(self, worker: DomainWorker) -> None:
        self.story = worker

    def start_all(self) -> None:
        if self.story is not None:
            self.story.start()
        self.memory.start()
        self.presence.start()
        if self.life is not None:
            self.life.start()
        self.persona.start()

    def stop_all(self) -> None:
        if self.life is not None:
            self.life.stop()
        if self.story is not None:
            self.story.stop()
        self.persona.stop()
        self.presence.stop()
        self.memory.stop()

    def status(self, *, orchestration: dict[str, Any] | None = None) -> dict[str, Any]:
        life_status = self.life.status() if self.life is not None else {"state": "unregistered", "queued": 0}
        story_status = self.story.status() if self.story is not None else {"state": "unregistered", "queued": 0}
        out = {
            "memory": self.memory.status(),
            "presence": self.presence.status(),
            "life": life_status,
            "story": story_status,
            "persona": self.persona.status(),
        }
        if orchestration is not None:
            out["orchestration"] = orchestration
        return out
