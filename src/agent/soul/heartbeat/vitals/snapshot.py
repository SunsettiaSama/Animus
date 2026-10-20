"""L2 体征层：把探针读数折叠成一组状态变量快照（SoulVitals）。

vitals 只记事实，不下判断——判断在 L3 policy。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from agent.soul.heartbeat.probe import (
    EvolutionWorkerProbe,
    HeartbeatSelfProbe,
    PresenceProbe,
    SoulProbe,
    SpeakProbe,
)


@dataclass(frozen=True)
class SoulVitals:
    """soul 生命体征变量组（心跳每轮可读、status 可暴露）。"""

    ts: str
    speaking: bool = False            # 正在说话（任一会话 turn/push 进行中）
    typing: bool = False              # 用户打字中（soul 侧等价信号）
    awake: bool = False               # presence 清醒
    evolving: bool = False            # 演化 worker 有任务在跑/排队
    heartbeat_failures: int = 0       # 心跳主循环连续失败
    thread_alive: bool = True         # 心跳线程存活
    inject_pending: bool = False      # 注入信箱/暂存有待注入
    unknown_parts: tuple[str, ...] = ()  # 读不到的部位（诚实标注）

    def as_dict(self) -> dict:
        return asdict(self)


class VitalsBuilder:
    """注册探针、折叠快照；同名探针后注册者替换前者（供 core 延迟挂接）。"""

    def __init__(self) -> None:
        self._probes: dict[str, SoulProbe] = {}

    def register(self, probe: SoulProbe) -> SoulProbe:
        self._probes[probe.name] = probe
        return probe

    def snapshot(self) -> SoulVitals:
        fields: dict = {}
        unknown: list[str] = []
        for probe in self._probes.values():
            reading = probe.sample()
            if not reading.ok:
                unknown.append(reading.name)
                continue
            fields.update(reading.fields)
        return SoulVitals(
            ts=datetime.now(timezone.utc).isoformat(),
            speaking=bool(fields.get("speaking", False)),
            typing=bool(fields.get("typing", False)),
            awake=bool(fields.get("awake", False)),
            evolving=bool(fields.get("evolving", False)),
            heartbeat_failures=int(fields.get("consecutive_failures", 0)),
            thread_alive=bool(fields.get("thread_alive", True)),
            inject_pending=bool(fields.get("inject_pending", False))
            or bool(fields.get("deferred_pending", False)),
            unknown_parts=tuple(unknown),
        )

    @classmethod
    def default(cls, *, soul=None, worker=None, core=None) -> "VitalsBuilder":
        """默认探针组：speak / presence / evolution worker / 心跳自身。"""
        builder = cls()
        builder.register(SpeakProbe(soul))
        builder.register(PresenceProbe(soul))
        builder.register(EvolutionWorkerProbe(worker))
        builder.register(HeartbeatSelfProbe(core))
        return builder
