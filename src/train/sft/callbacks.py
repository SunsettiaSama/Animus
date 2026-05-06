from __future__ import annotations

import math
import threading
from typing import TYPE_CHECKING

from transformers import TrainerCallback, TrainerControl, TrainerState, TrainingArguments

if TYPE_CHECKING:
    pass


class LossMonitorCallback(TrainerCallback):
    def __init__(
        self,
        loss_history: list[float],
        spike_threshold: float = 10.0,
        no_improve_steps: int = 0,
        abort_event: threading.Event | None = None,
    ) -> None:
        self._loss_history = loss_history
        self._spike_threshold = spike_threshold
        self._no_improve_steps = no_improve_steps
        self._abort_event = abort_event
        self._running_avg: float = 0.0
        self._best_loss: float = float("inf")
        self._no_improve_count: int = 0

    def on_log(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        logs: dict | None = None,
        **kwargs,
    ) -> None:
        if logs is None:
            return
        loss = logs.get("loss")
        if loss is None:
            return

        if math.isnan(loss) or math.isinf(loss):
            control.should_training_stop = True
            return

        self._loss_history.append(loss)

        n = len(self._loss_history)
        if n == 1:
            self._running_avg = loss
        else:
            self._running_avg = self._running_avg * 0.9 + loss * 0.1

        if self._spike_threshold > 0 and self._running_avg > 0:
            if loss > self._spike_threshold * self._running_avg:
                import sys
                print(
                    f"[LossMonitor] spike detected at step {state.global_step}: "
                    f"loss={loss:.4f} avg={self._running_avg:.4f}",
                    file=sys.stderr,
                    flush=True,
                )

        if self._no_improve_steps > 0:
            if loss < self._best_loss:
                self._best_loss = loss
                self._no_improve_count = 0
            else:
                self._no_improve_count += 1
            if self._no_improve_count >= self._no_improve_steps:
                control.should_training_stop = True

    def on_step_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ) -> None:
        if self._abort_event is not None and self._abort_event.is_set():
            control.should_training_stop = True
