"""phases — 启动五阶段模型（env → config → infra → soul → serve）。

阶段只描述"到哪一步了"，不负责探测；探测在 probes.py，聚合在 status.py。
"""
from __future__ import annotations

ENV = "env"          # Python / 依赖
CONFIG = "config"    # yaml 配置装载
INFRA = "infra"      # LLM / embedding / 存储后端
SOUL = "soul"        # SoulService 运行态（含 speak）
SERVE = "serve"      # 宿主在役（webui / 未来无头服务）

PHASES: list[tuple[str, str]] = [
    (ENV, "环境"),
    (CONFIG, "配置"),
    (INFRA, "基础设施"),
    (SOUL, "Soul"),
    (SERVE, "服务"),
]

# 阶段灯状态（前端渲染约定：ok 绿 / warn 黄 / fail 红 / pending 灰）
OK = "ok"
WARN = "warn"
FAIL = "fail"
PENDING = "pending"

PHASE_ORDER = {pid: i for i, (pid, _) in enumerate(PHASES)}
