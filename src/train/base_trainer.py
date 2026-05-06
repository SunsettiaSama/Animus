from __future__ import annotations

import sys
import threading
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TrainResult:
    adapter_path: str
    steps: int
    final_loss: float
    elapsed_secs: float
    run_id: str = ""
    report_url: str = ""
    loss_history: list[float] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class BaseTrainer(ABC):
    def __init__(self) -> None:
        self._loss_history: list[float] = []
        self._log_lines: deque[str] = deque(maxlen=500)
        self._status: str = "idle"
        self._current_step: int = 0
        self._abort_event: threading.Event = threading.Event()

    def _add_log(self, line: str) -> None:
        self._log_lines.append(line)
        print(f"[train] {line}", file=sys.stderr, flush=True)

    @abstractmethod
    def setup(self, model_name: str, **kwargs) -> None:
        raise NotImplementedError

    @abstractmethod
    def train(self, dataset) -> TrainResult:
        raise NotImplementedError

    @abstractmethod
    def save(self, output_dir: str) -> None:
        raise NotImplementedError

    def get_logs(self, n: int = 100) -> list[str]:
        lines = list(self._log_lines)
        return lines[-n:]

    def get_loss_history(self) -> list[float]:
        return list(self._loss_history)

    def get_metrics(self) -> dict:
        import torch

        gpu_mb = 0
        if torch.cuda.is_available():
            gpu_mb = torch.cuda.memory_allocated() // (1024 * 1024)
        return {
            "step":          self._current_step,
            "loss":          self._loss_history[-1] if self._loss_history else None,
            "gpu_memory_mb": gpu_mb,
        }

    def status(self) -> dict:
        return {
            "state":        self._status,
            "current_step": self._current_step,
            "loss":         self._loss_history[-1] if self._loss_history else None,
            "gpu_memory_mb": self.get_metrics()["gpu_memory_mb"],
        }
