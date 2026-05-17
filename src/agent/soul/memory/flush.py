from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.memory.unit import MemoryTier

if TYPE_CHECKING:
    from agent.soul.memory.short_term.manager import ShortTermMemoryManager
    from agent.soul.memory.long_term.manager import LongTermMemoryManager


@dataclass
class FlushResult:
    """FlushEngine.run() 的执行报告。"""
    flushed:  int = 0   # 成功写入 LTM 并从 STM 删除的条数
    skipped:  int = 0   # activation 低于 floor，留给 Redis TTL 自然淘汰的条数
    errors:   int = 0   # 处理中出现异常的条数
    ids_flushed:  list[str] = field(default_factory=list)
    ids_skipped:  list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"FlushResult(flushed={self.flushed}, "
            f"skipped={self.skipped}, errors={self.errors})"
        )


class FlushEngine:
    """STM → LTM 定期归档引擎。

    记忆生命周期管理的核心组件：

        STM（Redis）─── FlushEngine ──→ LTM（MySQL）
                                            │
                                        forget_scan
                                            │
                                         archived

    设计原则（路径 C）
    ------------------
    所有 STM 条目最终都会 flush 进 LTM——不设"是否值得保留"的门控，
    而是用 **activation 决定 LTM 初始 base_activation**：

    - activation < floor      → 跳过，让 Redis TTL 自然淘汰（噪声级别）
    - activation ∈ [floor, 1] → flush，以当前 activation 作为 base_activation 写入 LTM

    进入 LTM 后，forget_scan 定期清理长期不活跃的条目，高价值记忆
    （情绪强、被频繁召回、被叙事引用）自然在 forget_scan 中存活更久。

    这样，"晋升"这个决策被拆解为两件独立且更简单的事：
    1. flush 时设定合理的初始 base_activation（此 Engine 负责）
    2. LTM 内的长期遗忘（forget_scan 负责）

    调用方式
    --------
    由心跳任务定期调用（如每 12 小时）：

        result = flush_engine.run()
        print(result)

    参数
    ----
    stm
        短期记忆管理器（Redis）
    ltm
        长期记忆管理器（MySQL）
    stm_half_life_days
        STM 激活度计算使用的半衰期，与 ShortTermMemoryManager 配置一致
    activation_floor
        低于此 activation 的 STM 条目不进 LTM；建议值 0.05~0.15
    """

    def __init__(
        self,
        stm: ShortTermMemoryManager,
        ltm: LongTermMemoryManager,
        stm_half_life_days: float = 3.0,
        activation_floor: float = 0.1,
    ) -> None:
        self._stm = stm
        self._ltm = ltm
        self._half_life = stm_half_life_days
        self._floor = activation_floor

    def run(self) -> FlushResult:
        """执行一次 flush 扫描，返回执行报告。

        流程：
        1. 从 STM 取出所有未过期 unit
        2. 计算每条 unit 的当前 activation
        3. activation >= floor → 设 base_activation = activation，写入 LTM，从 STM 删除
        4. activation < floor → 跳过（让 Redis TTL 自然处理）
        """
        result = FlushResult()
        now = datetime.now(timezone.utc)
        units = self._stm.list_all()

        for unit in units:
            act = unit.activation(now=now, half_life_days=self._half_life)
            if act < self._floor:
                result.skipped += 1
                result.ids_skipped.append(unit.id)
                continue

            unit.base_activation = act
            unit.promote_to_long()       # tier = MemoryTier.long

            self._ltm.put(unit)
            self._stm.delete(unit.id)
            result.flushed += 1
            result.ids_flushed.append(unit.id)

        return result

