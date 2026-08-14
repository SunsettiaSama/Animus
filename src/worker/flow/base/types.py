from __future__ import annotations

from enum import Enum


class NodeStatus(str, Enum):
    """Generic DAG node lifecycle; values align with task execution in the flow layer."""

    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    paused = "paused"
