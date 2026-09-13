"""direct 管线的运行时可调参数与剧情帧/注意力债/去重支撑。

调参默认值可通过 config/agent/direct.yaml 覆盖（缺省即用内置默认）：

    max_frame_seconds: 120      # 剧情帧上限
    debt_soft_messages: 2       # 注意力债软线（仅材料提醒）
    debt_hard_messages: 3       # 硬线：越线禁止空输出（强制至少一个反应）
    debt_hard_seconds: 600.0    # 等待时长硬线
    dedup_similarity: 0.85      # 跨轮答案去重阈值
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from difflib import SequenceMatcher


@dataclass(frozen=True)
class DirectTuning:
    max_frame_seconds: float = 120.0
    debt_soft_messages: int = 2
    debt_hard_messages: int = 3
    debt_hard_seconds: float = 600.0
    dedup_similarity: float = 0.85
    runsheet_enabled: bool = True
    # 酝酿队列（brew）升级阈值：积压达到该深度时把条目注入编剧重排，
    # 由编剧把冲动合理化进剧情/唤醒理由；brew 自身永远不直接产生消息。
    brew_upgrade_depth: int = 2

    @classmethod
    def load(cls) -> "DirectTuning":
        import os

        # src/agent/soul/speak/responders/request_driven/character/frame.py
        #   → 上溯 7 层到仓库根，再找 config/agent/direct.yaml
        here = os.path.dirname(os.path.abspath(__file__))
        repo_root = here
        for _ in range(7):
            repo_root = os.path.dirname(repo_root)
        cfg_path = os.path.join(repo_root, "config", "agent", "direct.yaml")
        data: dict = {}
        try:
            import yaml

            with open(cfg_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except OSError:
            data = {}
        return cls(
            max_frame_seconds=float(data.get("max_frame_seconds", 120.0)),
            debt_soft_messages=int(data.get("debt_soft_messages", 2)),
            debt_hard_messages=int(data.get("debt_hard_messages", 3)),
            debt_hard_seconds=float(data.get("debt_hard_seconds", 600.0)),
            dedup_similarity=float(data.get("dedup_similarity", 0.85)),
            runsheet_enabled=bool(data.get("runsheet_enabled", True)),
            brew_upgrade_depth=max(1, int(data.get("brew_upgrade_depth", 2))),
        )


_FRAME_KEY = "direct.frame"
_DEBT_KEY = "debt.tracker"
_DEDUP_KEY = "dedup.recent"


def _cache(state: Any, key: str) -> dict[str, Any]:
    store = getattr(state, "director_cache", None)
    if not isinstance(store, dict):
        return {}
    raw = store.get(key)
    return dict(raw) if isinstance(raw, dict) else {}


def _write_cache(state: Any, key: str, data: dict[str, Any]) -> None:
    store = getattr(state, "director_cache", None)
    if isinstance(store, dict):
        store[key] = dict(data)


# ── 剧情帧 ───────────────────────────────────────────────────────────────────

def frame_meta(state: Any, tuning: DirectTuning, *, now: float | None = None) -> dict[str, Any]:
    """读取当前帧并按需开新帧；返回帧元数据（惰性边界，刷新由外部钩子承担）。

    frame_expired_this_turn=True 表示本次调用跨越了边界（首次建帧或超时重开）。
    """
    current = time.time() if now is None else float(now)
    fr = _cache(state, _FRAME_KEY)
    started = float(fr.get("started_at", 0.0))
    stale = started <= 0 or (current - started) > tuning.max_frame_seconds
    if stale:
        fr = {"started_at": current}
        _write_cache(state, _FRAME_KEY, fr)
    age = current - float(fr["started_at"])
    return {
        "frame_started_at": fr["started_at"],
        "frame_age": round(age, 3),
        "frame_expired_this_turn": stale,
    }


# ── 注意力债 ─────────────────────────────────────────────────────────────────

@dataclass
class DebtSnapshot:
    unanswered: int = 0
    wait_seconds: float = 0.0
    soft_exceeded: bool = False
    hard_exceeded: bool = False

    def material_lines(self) -> list[str]:
        lines: list[str] = []
        if self.unanswered <= 0:
            return lines
        wait = f"{self.wait_seconds:.0f} 秒" if self.wait_seconds < 90 else f"{self.wait_seconds / 60:.1f} 分钟"
        lines.append(f"对方已连续发来 {self.unanswered} 条消息，最早一条等了约 {wait}，还没有你的回应。")
        if self.hard_exceeded:
            lines.append("这已经是失礼的等待了。")
        elif self.soft_exceeded:
            lines.append("再不理会就要显得刻意了。")
        return lines


def note_debt_user_message(state: Any) -> DebtSnapshot:
    """用户入站记账：连续未回应则债务 +1，否则重置为 1。"""
    now = time.time()
    d = _cache(state, _DEBT_KEY)
    unanswered = int(d.get("unanswered", 0))
    first_pending_at = float(d.get("first_pending_at", 0.0))
    if unanswered <= 0 or first_pending_at <= 0:
        unanswered = 1
        first_pending_at = now
    else:
        unanswered += 1
    snapshot = _snapshot_with(unanswered=unanswered, first_pending_at=first_pending_at)
    _write_cache(state, _DEBT_KEY, {
        "unanswered": unanswered,
        "first_pending_at": first_pending_at,
    })
    return snapshot


def note_debt_agent_reply(state: Any) -> DebtSnapshot:
    """角色实际产出可见回应后清偿债务。空回应不算清偿。"""
    _write_cache(state, _DEBT_KEY, {"unanswered": 0, "first_pending_at": 0.0})
    return DebtSnapshot()


def current_debt(state: Any, *, now: float | None = None) -> DebtSnapshot:
    current = time.time() if now is None else float(now)
    d = _cache(state, _DEBT_KEY)
    return _snapshot_with(
        unanswered=int(d.get("unanswered", 0)),
        first_pending_at=float(d.get("first_pending_at", 0.0)),
        now=current,
    )


def _snapshot_with(
    *,
    unanswered: int,
    first_pending_at: float,
    now: float | None = None,
) -> DebtSnapshot:
    t = DirectTuning.load()
    current = time.time() if now is None else float(now)
    wait = max(0.0, current - first_pending_at) if first_pending_at > 0 else 0.0
    soft = unanswered >= t.debt_soft_messages or wait >= t.debt_hard_seconds / 2
    hard = unanswered >= t.debt_hard_messages or wait >= t.debt_hard_seconds
    return DebtSnapshot(
        unanswered=unanswered,
        wait_seconds=wait,
        soft_exceeded=bool(soft),
        hard_exceeded=bool(hard),
    )


# ── 跨轮去重 ─────────────────────────────────────────────────────────────────

def remember_answer(state: Any, answer: str, *, keep: int = 6) -> None:
    text = str(answer or "").strip()
    if not text:
        return
    d = _cache(state, _DEDUP_KEY)
    recent = [str(x) for x in (d.get("answers") or [])]
    recent.append(text[:800])
    d["answers"] = recent[-keep:]
    _write_cache(state, _DEDUP_KEY, d)


def find_duplicate(
    answer: str,
    candidates: Any,
    threshold: float | None = None,
) -> str:
    """在与候选旧答案的相似度中命中即返回该旧文本；无相似返回空串。"""
    t = DirectTuning.load()
    thr = t.dedup_similarity if threshold is None else float(threshold)
    candidate = str(answer or "").strip()
    if len(candidate) < 12:
        return ""
    for old in [str(x) for x in (candidates or [])]:
        ratio = SequenceMatcher(None, _normalize(candidate), _normalize(old)).ratio()
        if ratio >= thr:
            return old
    return ""


def _normalize(text: str) -> str:
    return "".join(ch for ch in str(text or "") if ch.strip())[:400]


def recent_answers(state: Any, *, keep: int = 6) -> tuple[str, ...]:
    d = _cache(state, _DEDUP_KEY)
    return tuple(str(x) for x in (d.get("answers") or [])[-keep:])
