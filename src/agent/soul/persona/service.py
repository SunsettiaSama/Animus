from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.react.prompt.block import PromptBlock

if TYPE_CHECKING:
    from agent.soul.persona.manager import PersonaManager
    from agent.soul.workers import DomainWorker


class PersonaService:
    """Persona service：profile / buffer 元数据 / self_concept。"""

    def __init__(self, manager: PersonaManager) -> None:
        self._manager = manager

    @property
    def manager(self) -> PersonaManager:
        return self._manager

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._manager.set_worker(worker)

    def set_memory_port(self, port) -> None:
        self._manager.set_memory_port(port)

    def set_embedder(self, embedder) -> None:
        self._manager.set_embedder(embedder)

    def snapshot(self) -> dict[str, Any]:
        return self._manager.snapshot()

    def buffer_snapshot(self, *, include_signals: bool = False) -> dict[str, Any]:
        return self._manager.buffer_snapshot(include_signals=include_signals)

    def record_cluster_signals(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """Memory.persona_clusters → buffer 元数据（漂移前的信号采集）。"""
        if not payloads:
            return {
                "ok": True,
                "applied": 0,
                "signal_ids": [],
                "buffer": self.buffer_snapshot(),
            }
        return self._manager.record_cluster_signals(payloads)

    def run_monthly_drift(self, *, force: bool = False, month: str = "") -> dict[str, Any]:
        """唯一 self_concept 漂移入口：buffer → 聚类蒸馏 → 修订写回。"""
        return self._manager.run_monthly_drift(force=force, month=month)

    def portrait_revision(self) -> str:
        return self._manager.portrait_revision()

    def portrait_for_narrative(
        self,
        max_chars: int = 1200,
        *,
        compact: bool = False,
    ) -> str:
        return self._manager.portrait_for_narrative(max_chars=max_chars, compact=compact)

    def all_blocks(self) -> list[PromptBlock]:
        return self._manager.all_blocks()

    def bias_query(self, query: str) -> str:
        return self._manager.bias_query(query)

    def reset_self_concept(self) -> None:
        """管理操作：清空 self_concept 与 buffer（非漂移）。"""
        self._manager.reset_self_concept()

    def reload_profile(self) -> dict[str, Any]:
        return self._manager.reload_profile()

    def rebuild_profile(self, *, preserve_self_concept: bool = False) -> dict[str, Any]:
        return self._manager.rebuild_profile(
            preserve_self_concept=preserve_self_concept,
        )
