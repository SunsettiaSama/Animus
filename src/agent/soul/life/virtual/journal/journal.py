from __future__ import annotations

from datetime import datetime, timezone

from .item import K_RECENT_LANDMARKS, MAX_DAILY_LANDMARKS, Landmark, LandmarkStatus


class LifeJournal:
    """Agent 的手账——地标时间轴 + 自述叙事。

    手账是 Agent 面向自身的规划与表达空间。

    两个维度
    --------
    1. **地标轴（Landmarks）**：Agent 每天预约 1~``MAX_DAILY_LANDMARKS`` 个叙事
       体验时刻，每个地标到点后由 ``LandmarkFiller`` 填充为完整情节并内化为
       ``ExperienceUnit``。
    2. **自述（Narrative）**：Agent 对这段时间经历的自由文字表达，
       由 Agent 在内省时主动写入。

    手账不主动构造任何体验，也不推断叙事状态。
    它只持有 Agent 留下的记录，供 Agent 和 LifeService 随时查阅。
    """

    def __init__(
        self,
        landmarks: list[Landmark] | None = None,
        self_narrative: str = "",
    ) -> None:
        self._landmarks: list[Landmark] = landmarks or []
        self._narrative: str = self_narrative

    # ── 地标管理 ──────────────────────────────────────────────────────────────

    def add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> Landmark | None:
        """新增一个地标，若今日已达上限则返回 None。"""
        today = datetime.now(timezone.utc).date().isoformat()
        today_count = sum(
            1 for lm in self._landmarks
            if lm.created_at[:10] == today
            and lm.status != LandmarkStatus.done
        )
        if today_count >= MAX_DAILY_LANDMARKS:
            return None
        lm = Landmark(intention=intention, scheduled_at=scheduled_at, context=context)
        self._landmarks.append(lm)
        return lm

    def get_landmark(self, landmark_id: str) -> Landmark | None:
        for lm in self._landmarks:
            if lm.id == landmark_id:
                return lm
        return None

    def due_landmarks(self) -> list[Landmark]:
        """返回已到触发时间但尚未处理的地标（pending / overdue）。"""
        return [lm for lm in self._landmarks if lm.is_due()]

    def scan_overdue(self) -> list[Landmark]:
        """扫描并标记所有超时地标，返回标记后的列表（服务重启时调用）。"""
        overdue: list[Landmark] = []
        for lm in self._landmarks:
            if lm.status == LandmarkStatus.pending and lm.is_due():
                lm.mark_overdue()
                overdue.append(lm)
        return overdue

    def recent_done(self, n: int = K_RECENT_LANDMARKS) -> list[Landmark]:
        """返回最近 n 个已完成的地标（按创建时间倒序），供编排新地标时作上下文。"""
        done = [lm for lm in self._landmarks if lm.status == LandmarkStatus.done]
        done.sort(key=lambda lm: lm.created_at, reverse=True)
        return done[:n]

    def today_landmarks(self) -> list[Landmark]:
        today = datetime.now(timezone.utc).date().isoformat()
        return [lm for lm in self._landmarks if lm.created_at[:10] == today]

    def today_remaining_slots(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        active_today = sum(
            1 for lm in self._landmarks
            if lm.created_at[:10] == today
            and lm.status != LandmarkStatus.done
        )
        return max(0, MAX_DAILY_LANDMARKS - active_today)

    def count_written_since(self, since: datetime) -> int:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        count = 0
        for lm in self._landmarks:
            created = datetime.fromisoformat(lm.created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= since:
                count += 1
        return count

    def all_landmarks(self) -> list[Landmark]:
        return list(self._landmarks)

    # ── 自述 ──────────────────────────────────────────────────────────────────

    @property
    def self_narrative(self) -> str:
        return self._narrative

    def set_narrative(self, text: str) -> None:
        self._narrative = text

    # ── 状态检查 ──────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        live = [
            lm for lm in self._landmarks
            if lm.status in (LandmarkStatus.pending, LandmarkStatus.overdue)
        ]
        return not live and not self._narrative

    # ── Prompt 注入 ───────────────────────────────────────────────────────────

    def to_digest(self) -> str:
        """生成可注入 prompt 的手账摘要。"""
        parts: list[str] = []

        if self._narrative:
            parts.append(f"【自述】\n{self._narrative}")

        today = self.today_landmarks()
        if today:
            lines = ["【今日地标】"]
            for lm in today:
                tag = {
                    LandmarkStatus.pending:    "○",
                    LandmarkStatus.processing: "◐",
                    LandmarkStatus.done:       "●",
                    LandmarkStatus.overdue:    "⚑",
                }.get(lm.status, "·")
                scheduled = lm.scheduled_at[11:16] if len(lm.scheduled_at) > 16 else lm.scheduled_at
                lines.append(f"  {tag} [{scheduled}] {lm.intention}")
                if lm.context:
                    lines.append(f"       {lm.context}")
            parts.append("\n".join(lines))

        recent = self.recent_done(3)
        if recent:
            lines = ["【近期经历】"]
            for lm in recent:
                snippet = lm.narrative[:60] if lm.narrative else lm.intention
                lines.append(f"  · {snippet}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "landmarks":      [lm.to_dict() for lm in self._landmarks],
            "self_narrative": self._narrative,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeJournal:
        landmarks = [Landmark.from_dict(lm) for lm in d.get("landmarks", [])]
        return cls(landmarks=landmarks, self_narrative=d.get("self_narrative", ""))
