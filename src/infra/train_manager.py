from __future__ import annotations

import dataclasses
import sys
import threading
import time
from typing import TYPE_CHECKING, Literal

from infra.base_service import BaseServiceManager

if TYPE_CHECKING:
    from train.base_trainer import BaseTrainer, TrainResult
    from train.data.dataset import TrainDataset


class TrainJobManager(BaseServiceManager):
    """Manages a training job as a background thread.

    Mirrors VLLMServerManager's lifecycle pattern and registers with
    ServiceRegistry so the WebUI /api/services/* endpoints expose training
    state, loss history, and adapter path without extra API work.

    State machine::

        idle ──start()──► running ──complete──► idle
                              └──error──► error
                              └──stop()──► interrupted
        interrupted ──start(..., resume=True)──► running
    """

    def __init__(self) -> None:
        self._state: Literal["idle", "running", "interrupted", "error"] = "idle"
        self._trainer: BaseTrainer | None = None
        self._result: TrainResult | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(
        self,
        trainer: BaseTrainer | None = None,
        dataset: TrainDataset | None = None,
        overrides: dict | None = None,
        resume: bool = False,
        **kwargs,
    ) -> None:
        with self._lock:
            if self._state == "running":
                return
            if trainer is None and self._trainer is None:
                raise ValueError("trainer must be provided on first call to start()")
            if trainer is not None:
                self._trainer = trainer
            if not resume:
                self._result = None
                self._trainer._loss_history.clear()
                self._trainer._abort_event.clear()

        if overrides and self._trainer is not None:
            cfg_attr = "_sft_cfg"
            if hasattr(self._trainer, cfg_attr):
                old_cfg = getattr(self._trainer, cfg_attr)
                setattr(self._trainer, cfg_attr, dataclasses.replace(old_cfg, **overrides))

        with self._lock:
            self._state = "running"

        self._thread = threading.Thread(
            target=self._run,
            args=(dataset,),
            daemon=True,
            name="train-job",
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._state != "running":
                return
            trainer = self._trainer

        if trainer is not None:
            trainer._abort_event.set()

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            with self._lock:
                if self._state != "running":
                    return
            time.sleep(0.5)

        with self._lock:
            self._state = "interrupted"

    def status(self) -> dict:
        import torch

        with self._lock:
            state   = self._state
            trainer = self._trainer
            result  = self._result

        gpu_mb = 0
        if torch.cuda.is_available():
            gpu_mb = torch.cuda.memory_allocated() // (1024 * 1024)

        metrics = trainer.get_metrics() if trainer else {}
        return {
            "state":          state,
            "current_step":   metrics.get("step", 0),
            "loss":           metrics.get("loss"),
            "gpu_memory_mb":  gpu_mb,
            "adapter_path":   result.adapter_path if result else None,
            "elapsed_secs":   result.elapsed_secs if result else None,
        }

    def get_logs(self, n: int = 100) -> list[str]:
        with self._lock:
            trainer = self._trainer
        return trainer.get_logs(n) if trainer else []

    # ── Extended interface ────────────────────────────────────────────────────

    def get_loss_history(self) -> list[float]:
        with self._lock:
            trainer = self._trainer
        return trainer.get_loss_history() if trainer else []

    def get_result(self) -> TrainResult | None:
        with self._lock:
            return self._result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, dataset: TrainDataset | None) -> None:
        trainer = self._trainer
        if trainer is None or dataset is None:
            with self._lock:
                self._state = "error"
            print("[TrainJobManager] trainer or dataset is None", file=sys.stderr)
            return

        result = trainer.train(dataset)
        with self._lock:
            if self._state == "running":
                self._state = "idle"
            self._result = result
