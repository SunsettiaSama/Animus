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

# 参与碰撞检测的来源类型
_COLLISION_SOURCES: frozenset[str] = frozenset({"user", "narrative", "surprise"})

# 碰撞扫描的最大候选数量（避免 O(n) 全扫）
_COLLISION_SCAN_LIMIT = 20


class MemoryIngestPort(Protocol):
    """编排器向记忆层写入的抽象接口，由上层 MemoryService 适配实现。"""

    def ingest_experience(self, unit: ExperienceUnit) -> None: ...


class ExperienceOrchestrator:
    """体验编排层（纯机械层）：热存储 + 即时/批量擢升 + 多路交会折叠。

    职责
    ----
    - 接收已由 ``ExperienceBuilder`` 构造的 ``ExperienceUnit``
    - 写入 ``ExperienceLog`` 热存储
    - 按显著性阈值即时或批量触发向 ``MemoryIngestPort`` 的擢升
    - 心跳驱动的清仓（purge_old）
    - **多路交会折叠**：当 ``{user, narrative, surprise}`` 中的
      两路或三路体验在 ``collision_window_min`` 分钟内相遇，
      调用 ``ExperienceCollapser`` 生成交会叙事，
      产出 ``source="collision"`` 的新体验单元

    折叠规则
    --------
    - 检测范围：热存储最近 ``_COLLISION_SCAN_LIMIT`` 条
    - 每路来源最多取一个代表单元（先到先得，已折叠的跳过）
    - 2路或3路均支持；collision unit 不再参与折叠检测
    - 折叠后原始单元标记为已折叠（内存集合，服务重启后重置）
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
        """写入热存储；若显著性达阈值立即擢升；检测多路交会折叠。"""
        self._log.append(unit)
        if unit.is_salient(self._salience_threshold):
            self._promote(unit)
        if (
            self._collapser is not None
            and unit.source in _COLLISION_SOURCES
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

    # ── 多路交会折叠 ──────────────────────────────────────────────────────────

    def _maybe_collapse(self, incoming: ExperienceUnit) -> None:
        """扫描热存储，收集与 incoming 在时间窗口内且来源不同的体验，触发折叠。"""
        other_sources = _COLLISION_SOURCES - {incoming.source}
        incoming_ts   = _parse_ts(incoming.ts)

        partners: list[ExperienceUnit] = []
        seen_sources: set[str] = {incoming.source}

        candidates = self._log.recent()[-_COLLISION_SCAN_LIMIT:]
        for candidate in reversed(candidates):
            if candidate.id == incoming.id:
                continue
            if candidate.id in self._collapsed_ids:
                continue
            if candidate.source not in other_sources:
                continue
            if candidate.source in seen_sources:
                continue  # 每路来源只取一个代表
            delta = abs((incoming_ts - _parse_ts(candidate.ts)).total_seconds())
            if delta <= self._collision_window_sec:
                partners.append(candidate)
                seen_sources.add(candidate.source)

        if partners:
            self._do_collapse([incoming] + partners)

    def _do_collapse(self, units: list[ExperienceUnit]) -> None:
        """执行交会折叠：Collapser → collision unit → 入库 → 标记已折叠。"""
        merged_text = self._collapser.collapse(units)  # type: ignore[union-attr]

        # 优先用 user unit 的 session 信息作为 collision unit 的来源标识
        user_units = [u for u in units if u.source == "user"]
        ref = user_units[0] if user_units else units[0]

        prior_parts = [
            f"[{u.source}] {(u.situation.perception or u.situation.narration or u.action.content)[:40]}"
            for u in units
        ]

        collision_unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id=ref.situation.session_id,
                turn_index=ref.situation.turn_index,
                narration=merged_text,
                prior_thought="；".join(prior_parts),
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.deciding,
                content=merged_text,
            ),
            feeling=ExperienceFeeling(),  # 全部清零，由叙事文本本身承载情绪
            source="collision",
        )

        self._log.append(collision_unit)
        if collision_unit.is_salient(self._salience_threshold):
            self._promote(collision_unit)

        for u in units:
            self._collapsed_ids.add(u.id)

    # ── 擢升 ──────────────────────────────────────────────────────────────────

    def _promote(self, unit: ExperienceUnit) -> None:
        if self._memory_port is not None:
            self._memory_port.ingest_experience(unit)


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
