"""演化 worker 探针：evolving（线程在跑且有任务）。"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.probe.base import SoulProbe


class EvolutionWorkerProbe(SoulProbe):
    name = "evolution_worker"

    def __init__(self, worker) -> None:
        self._worker = worker

    def _sample(self) -> dict[str, Any]:
        if self._worker is None:
            raise RuntimeError("evolution worker 未接线")
        status = self._worker.status()
        queued = int(status.get("queued") or 0)
        pending = int(len(status.get("pending_item_ids") or []))
        running = str(status.get("state")) == "running"
        return {
            "evolving": running and (queued > 0 or pending > 0),
            "worker_state": str(status.get("state", "")),
            "worker_queued": queued,
        }
