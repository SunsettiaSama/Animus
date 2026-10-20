"""记忆观测（memory telemetry）配置。

独立于 ``MemoryServiceConfig`` 读取 ``config/soul/memory/service.yaml`` 的
``telemetry:`` 组——观测开关不与记忆服务行为参数混在一起（PRD R1.4）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryTelemetryConfig:
    enabled: bool = True
    # 事件流水与快照的根目录（相对路径按进程 CWD 解析，与 .react 其余约定一致）
    dir: str = ".react/telemetry"
    events_filename: str = "memory_events.jsonl"
    # 单代事件文件上限（字节），超过后单代轮转（.1 覆盖旧代）
    max_events_bytes: int = 5_000_000
    # 进程内事件队列上限；满时丢最旧并计数，绝不阻塞调用方（PRD R1.3）
    queue_size: int = 4096
    snapshot_dirname: str = "snapshots"

    @property
    def events_path(self) -> Path:
        return Path(self.dir) / self.events_filename

    @property
    def snapshot_dir(self) -> Path:
        return Path(self.dir) / self.snapshot_dirname

    @classmethod
    def from_dict(cls, d: dict | None) -> "MemoryTelemetryConfig":
        data = dict(d or {})
        return cls(
            enabled=bool(data.get("enabled", True)),
            dir=str(data.get("dir", ".react/telemetry")),
            events_filename=str(data.get("events_filename", "memory_events.jsonl")),
            max_events_bytes=int(float(data.get("max_events_mb", 5)) * 1_000_000),
            queue_size=int(data.get("queue_size", 4096)),
            snapshot_dirname=str(data.get("snapshot_dirname", "snapshots")),
        )

    @classmethod
    def load_default(cls) -> "MemoryTelemetryConfig":
        """读 config/soul/memory/service.yaml 的 telemetry 组；文件缺失用默认值。

        环境变量 REACT_MEMORY_TELEMETRY 可整体开关（"0"/"off" 关，其余开），
        供测试与临时静默，不落配置文件。
        """
        cfg = cls()
        path = _default_yaml_path()
        if path.is_file():
            try:
                import yaml

                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                group = data.get("telemetry")
                if isinstance(group, dict):
                    cfg = cls.from_dict(group)
            except Exception:
                cfg = cls()
        override = os.environ.get("REACT_MEMORY_TELEMETRY", "").strip().lower()
        if override in ("0", "off", "false", "no"):
            cfg.enabled = False
        elif override in ("1", "on", "true", "yes"):
            cfg.enabled = True
        return cfg


def _default_yaml_path() -> Path:
    here = Path(__file__).resolve()
    # src/agent/soul/memory/telemetry/config.py → 仓库根
    root = here.parents[5]
    return root / "config" / "soul" / "memory" / "service.yaml"
