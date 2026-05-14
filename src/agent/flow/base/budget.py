from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .components.node_spec import NodeManifest


class TopologyKind(str, Enum):
    atomic = "atomic"   # I/O 明确，可直接交给 executor
    flat   = "flat"     # 展开为同层兄弟节点（广度方向）
    nested = "nested"   # 展开为私有子图（深度方向）


@dataclass(frozen=True)
class DecompositionBudget:
    """控制原子规划层递归展开的上限。

    每进入一层嵌套时，Orchestrator 将 max_depth - 1 后向下传递；
    max_depth == 0 时强制视当前节点为 atomic（不再展开）。

    Attributes
    ----------
    max_depth:
        最大嵌套深度。顶层为 depth=max_depth，叶节点为 depth=0。
        默认 3（战略层 → 战术层 → 原子层）。
    max_width:
        同一层展开后最多生成的兄弟节点数。超出时 AtomicPlanner 应
        继续向下嵌套而非横向平铺。默认 8。
    max_atom_steps:
        一个节点被判断为 atomic 的最大预期 TAO 步数。
        预期步数 ≤ 此值时无需展开。默认 5。
    """

    max_depth: int = 3
    max_width: int = 8
    max_atom_steps: int = 5
    max_review_rounds: int = 1

    def descend(self) -> "DecompositionBudget":
        """返回深度减一的子预算（进入嵌套子图时使用）。"""
        return DecompositionBudget(
            max_depth=max(0, self.max_depth - 1),
            max_width=self.max_width,
            max_atom_steps=self.max_atom_steps,
            max_review_rounds=self.max_review_rounds,
        )

    @property
    def exhausted(self) -> bool:
        """预算耗尽（depth == 0），不允许继续展开。"""
        return self.max_depth == 0

    @property
    def review_enabled(self) -> bool:
        """是否启用审查循环。"""
        return self.max_review_rounds > 0


# ── 确定性原子化判断 ───────────────────────────────────────────────────────────

_COMPOSITE_KEYWORDS = frozenset(
    {"以及", "并且", "同时", "另外", "还需要", "and also", "as well as",
     "additionally", "furthermore", "moreover"}
)


def is_atomic(manifest: "NodeManifest", budget: DecompositionBudget) -> bool:
    """确定性（无 LLM）判断节点是否已达原子粒度。

    所有条件均满足时返回 True：

    1. 预算已耗尽（强制原子化，防止无限递归）。
    2. input_contract 和 output_contract 均非空（I/O 已明确声明）。
    3. max_steps 已声明且 ≤ budget.max_atom_steps。
    4. description 中不含"复合职责"关键词。
    5. sub_manifests 已由上层填写（说明已经展开过，直接执行）。

    注意：此函数只做快速排除；当它返回 False 时，AtomicPlanner
    会进一步调用 LLM 做细粒度判断并决定 topology。
    """
    if budget.exhausted:
        return True

    # 已有子图声明 → 已展开，当前节点作为容器直接调度子图
    if manifest.sub_manifests:
        return True

    # I/O 未声明
    if not manifest.input_contract.strip() or not manifest.output_contract.strip():
        return False

    # 步数超预算
    if manifest.max_steps is not None and manifest.max_steps > budget.max_atom_steps:
        return False

    # 复合职责关键词
    desc_lower = manifest.description.lower()
    if any(kw in desc_lower for kw in _COMPOSITE_KEYWORDS):
        return False

    return True
