from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.soul.memory.service_config import MemoryServiceConfig
from infra.db.mysql import MySQLClient
from infra.llm import BaseLLM
from infra.memory import MemoryInfraService

from agent.soul.memory.graph.networks.store.codec import unit_to_dict
from agent.soul.memory.service import MemoryBlock, MemoryService
from config.soul.config import SoulConfig
from agent.soul.ports import LLMServicePort

from ._llm import resolve_module_llm
from .actions import MemoryAction

if TYPE_CHECKING:
    from agent.soul.workers import DomainWorker

__all__ = ["MemoryAction", "MemoryHandler"]


class MemoryHandler:
    """Memory API Handler：模块 LLM 直调 + MemoryService。"""

    DEFAULT_AUX_NAME = "memory"

    def __init__(
        self,
        mysql_client: MySQLClient,
        llm_service: LLMServicePort | None = None,
        llm_aux_name: str = DEFAULT_AUX_NAME,
        primary_llm: BaseLLM | None = None,
        cfg: MemoryServiceConfig | None = None,
        soul_config: SoulConfig | None = None,
        memory_infra: MemoryInfraService | None = None,
    ) -> None:
        self._mysql_client = mysql_client
        self._llm_service = llm_service
        self._llm_aux_name = llm_aux_name
        self._primary_llm = primary_llm
        self._cfg = cfg
        self._soul_config = soul_config
        self._memory_infra = memory_infra
        self._service: MemoryService | None = None
        self._worker: DomainWorker | None = None

    def set_worker(self, worker: DomainWorker) -> None:
        self._worker = worker
        if self._service is not None:
            self._service.set_worker(worker)

    def resolve_llm(self) -> BaseLLM | None:
        return resolve_module_llm(
            self._llm_service, self._llm_aux_name, self._primary_llm
        )

    @property
    def api(self) -> MemoryService:
        return self._ensure_service()

    def _ensure_service(self) -> MemoryService:
        if self._service is None:
            if self._soul_config is None:
                raise RuntimeError("MemoryHandler 需要 soul_config，请由 SoulService 注入")
            llm = self.resolve_llm()
            if llm is None:
                raise RuntimeError("Memory service unavailable — no LLM resolved")
            cfg = self._cfg or MemoryServiceConfig.load_default()
            infra = self._memory_infra or MemoryInfraService.build()
            self._service = MemoryService.build(
                llm=llm,
                mysql_client=self._mysql_client,
                cfg=cfg,
                memory_infra=infra,
            )
            if self._worker is not None:
                self._service.set_worker(self._worker)
        return self._service

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        service = self._ensure_service()

        if action == MemoryAction.RECALL:
            block = service.recall(**payload)
            return {"text": block.render()}

        if action == MemoryAction.SEARCH:
            payload = dict(payload)
            mode = str(payload.pop("mode", "hybrid"))
            results = service.search(mode, **payload)
            return {"mode": mode, "count": len(results), "results": results}

        if action == MemoryAction.NARRATIVE_CONTINUITY:
            lines = service.continuity_for_narrative(str(payload.get("query", "")))
            return {"count": len(lines), "lines": lines}

        if action == MemoryAction.FORGET_SCAN:
            archived = service.forget_scan(
                threshold=payload.get("threshold"),
                dry_run=bool(payload.get("dry_run", False)),
            )
            return {"archived": len(archived), "unit_ids": archived}

        if action == MemoryAction.SLEEP:
            result = service.run_sleep(
                tick_id=str(payload.get("tick_id", "")),
                dry_run=bool(payload.get("dry_run", False)),
                forget_threshold=payload.get("threshold"),
            )
            return result.to_dict()

        if action == MemoryAction.FLUSH:
            archived = service.forget_scan()
            return {"archived": len(archived), "unit_ids": archived}

        if action == MemoryAction.FETCH_PERSONA_CLUSTER:
            return service.fetch_persona_cluster(
                str(payload.get("theme", "")),
                unit_ids=list(payload.get("unit_ids") or []) or None,
                cluster_key=str(payload.get("cluster_key", "")),
            )

        if action == MemoryAction.LIST_DRIFT_UNITS:
            units = service.list_drift_units(
                month=str(payload.get("month", "")),
                anchor_unit_ids=list(payload.get("anchor_unit_ids") or []) or None,
                limit=int(payload.get("limit", 120)),
            )
            return {
                "count": len(units),
                "units": [unit_to_dict(u) for u in units],
            }

        if action == MemoryAction.GET_ACTIVATION_SNAPSHOT:
            snap = service.get_activation_snapshot(str(payload.get("session_id", "")))
            if snap is None:
                return {"session_id": payload.get("session_id", ""), "nodes": []}
            return {
                "session_id": snap.session_id,
                "interactor_id": snap.interactor_id,
                "cue_hash": snap.cue_hash,
                "nodes": [
                    {
                        "unit_id": n.unit_id,
                        "network": n.network.value,
                        "score": n.score,
                        "hop": n.hop,
                    }
                    for n in snap.nodes
                ],
            }

        if action == MemoryAction.GET_POINT_EMERGENCE:
            session_id = str(payload.get("session_id", ""))
            turn_index = int(payload.get("turn_index", 0) or 0)
            result = service.get_point_emergence(session_id, turn_index)
            if result is None:
                return {
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "precise_lines": [],
                    "associative_lines": [],
                }
            return {
                "session_id": result.session_id,
                "turn_index": result.turn_index,
                "associative_ready": result.associative_ready,
                "precise_lines": list(result.precise_lines),
                "associative_lines": list(result.associative_lines),
                "unit_ids": result.merged_unit_ids(),
            }

        raise ValueError(f"unknown memory action: {action!r}")
