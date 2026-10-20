"""心跳调用上下文：target 执行时由 orchestrator 构造并传入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class HeartbeatContext:
    """实现方可依赖的环境（只读）；实现细节自备，heartbeat 不注入模块知识。"""

    soul: Any                                # SoulService 实例
    orchestrator: Any = None                 # 调度器自身句柄（submit_heavy 临时重任务）
    scheduler_engine: Any = None             # 已绑定的调度引擎（可选）
    vitals_provider: Callable[[], Any] | None = None  # 生命体征读口（可选）
