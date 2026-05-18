from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

from .experience.log import ExperienceLog
from .experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)

if TYPE_CHECKING:
    from .experience.collapser import ExperienceCollapser

# 碰撞检测扫描的最大候选数量（避免 O(n) 全扫）
_COLLISION_SCAN_LIMIT = 20


class MemoryIngestPort(Protocol):
    """编排器向记忆层写入的抽象接口，由上层 MemoryService 适配实现。"""

    def ingest_experience(self, unit: ExperienceUnit) -> None: ...


class ExperienceOrchestrator:
    """体验编排层（纯机械层）：热存储 + 即时/批量擢升 + 交会折叠。

    职责
    ----
    - 接收已由 ``ExperienceBuilder`` 构造的 ``ExperienceUnit``
    - 写入 ``ExperienceLog`` 热存储
    - 按显著性阈值即时或批量触发向 ``MemoryIngestPort`` 的擢升
    - 心跳驱动的清仓（purge_old）
    - **交会折叠**：当 ``source="user"`` 与 ``source="narrative"`` 的体验
      在时间上相距不足 ``collision_window_min`` 分钟时，调用
      ``ExperienceCollapser`` 生成交会叙事，创建新的 ``source="collision"``
      体验单元，原始两个单元标记为已折叠

    入口
    ----
    - ``ingest(unit)``   — 主写入路径
    - ``tick()``         — 心跳批处理（扫描 + 擢升 + 清仓）
    - ``hot_window()``   — 只读热存储快照
    """

    def __init__(
        self,
        log: ExperienceLog,
        memory_port: MemoryIngestPort | None = None,
        salience_threshold: float = 0.5,
        collapser: ExperienceCollapser | None = None,
        collision_window_min: int = 30,
    ) -> None:
        self._log = log
        self._memory_port = memory_port
        self._salience_threshold = salience_threshold
        self._collapser = collapser
        self._collision_window_sec = collision_window_min * 60
        self._collapsed_ids: set[str] = set()

    def set_collapser(self, collapser: ExperienceCollapser) -> None:
        """热注入交会折叠器实现（LLM 就绪后调用）。"""
        self._collapser = collapser

    # ── 主写入路径 ────────────────────────────────────────────────────────────

    def ingest(self, unit: ExperienceUnit) -> None:
        """写入热存储；若显著性达阈值立即擢升；检测交会折叠。"""
        self._log.append(unit)
        if unit.is_salient(self._salience_threshold):
            self._promote(unit)
        if (
            self._collapser is not None
            and unit.source in ("user", "narrative")
            and unit.id not in self._collapsed_ids
        ):
            self._maybe_collapse(unit)

    # ── 心跳批处理 ────────────────────────────────────────────────────────────

    def tick(self) -> list[ExperienceUnit]:
        """心跳驱动：批量检查热存储中的擢升候选，清仓过期体验。"""
        hot = self._log.recent()
        promoted: list[ExperienceUnit] = []
        for unit in hot:
            if unit.is_salient(self._salience_threshold):
                self._promote(unit)
                promoted.append(unit)
        self._log.purge_old()
        return promoted

    def hot_window(self) -> list[ExperienceUnit]:
        """返回当前热存储窗口内的所有体验单元（只读快照）。"""
        return self._log.recent()

    # ── 交会折叠 ──────────────────────────────────────────────────────────────

    def _maybe_collapse(self, incoming: ExperienceUnit) -> None:
        """检查最近热存储，看是否有另一路来源的体验在时间窗口内相遇。"""
        target_source = "narrative" if incoming.source == "user" else "user"
        incoming_ts = _parse_ts(incoming.ts)

        candidates = self._log.recent()[-_COLLISION_SCAN_LIMIT:]
        for candidate in reversed(candidates):
            if candidate.id == incoming.id:
                continue
            if candidate.id in self._collapsed_ids:
                continue
            if candidate.source != target_source:
                continue
            delta = abs((incoming_ts - _parse_ts(candidate.ts)).total_seconds())
            if delta <= self._collision_window_sec:
                self._do_collapse(incoming, candidate)
                return

    def _do_collapse(self, unit_a: ExperienceUnit, unit_b: ExperienceUnit) -> None:
        """执行交会折叠：调用 Collapser → 生成 collision 体验单元 → 入库。"""
        user_unit      = unit_a if unit_a.source == "user" else unit_b
        narrative_unit = unit_b if unit_b.source == "narrative" else unit_a

        merged_text = self._collapser.collapse(user_unit, narrative_unit)  # type: ignore[union-attr]

        collision_unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id=user_unit.situation.session_id,
                turn_index=user_unit.situation.turn_index,
                narration=merged_text,
                prior_thought=(
                    f"用户对话：{user_unit.situation.perception[:40]}；"
                    f"叙事意图：{narrative_unit.situation.narration[:40]}"
                ),
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.deciding,
                content=merged_text,
            ),
            feeling=ExperienceFeeling(),  # 情感字段全部清零，由叙事文本本身承载
            source="collision",
        )

        # 直接写入，不再触发交会检测（source="collision" 不在检测范围内）
        self._log.append(collision_unit)
        if collision_unit.is_salient(self._salience_threshold):
            self._promote(collision_unit)

        self._collapsed_ids.add(unit_a.id)
        self._collapsed_ids.add(unit_b.id)

    # ── 擢升 ──────────────────────────────────────────────────────────────────

    def _promote(self, unit: ExperienceUnit) -> None:
        if self._memory_port is not None:
            self._memory_port.ingest_experience(unit)


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
