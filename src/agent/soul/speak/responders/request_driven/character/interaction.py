from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..protocol.blocks import strip_model_think, strip_role_tag_debris

_CACHE_KEY = "character_interaction_record"
_MAX_RECENT = 12
# 旧版沉默占位行：只用于识别并清洗历史数据，新账本不再写入
_USER_SILENCE_MARK = "对方：【......（没有说话）】"
_AGENT_SILENCE_MARK = "你：【......（没有说话）】"
_SILENCE_MARKS = (_USER_SILENCE_MARK, _AGENT_SILENCE_MARK)
_USER_PREFIXES = ("用户：", "用户:", "U:", "u:", "对方：", "对方:")
_AGENT_MARKERS = ("｜角色：", "|角色：", "角色：", "A:", "a:")


def _is_silence_mark(line: str) -> bool:
    return str(line or "").strip() in _SILENCE_MARKS


def _fmt_duration(sec: float) -> str:
    sec = max(0.0, float(sec))
    if sec < 90:
        return f"约 {sec:.0f} 秒"
    if sec < 3600:
        return f"约 {sec / 60:.0f} 分钟"
    return f"约 {sec / 3600:.1f} 小时"


def _user_side_only(raw: str) -> str:
    """编剧侧只留用户入站，丢掉角色台词。"""
    line = str(raw or "").strip()
    if not line:
        return ""
    for marker in _AGENT_MARKERS:
        if marker in line:
            line = line.split(marker, 1)[0].strip()
            break
    for prefix in _USER_PREFIXES:
        if line.startswith(prefix):
            line = line[len(prefix):].strip()
            break
    if not line:
        return ""
    if line.startswith(_AGENT_MARKERS):
        return ""
    return line


@dataclass
class InteractionRecord:
    """角色侧交互记录：编剧/导演向角色请求时的统一出口。

    用户热路径故意不阻塞等编剧同步；编剧与导演需要最新交互时，
    通过 export_interaction_record 向角色侧取这份记录。
    导演请求不到（空账本）就先产出，不得反向阻塞角色接口。
    """

    last_user_text: str = ""
    last_user_speak_at: float = 0.0
    last_agent_text: str = ""
    last_agent_speak_at: float = 0.0
    dialogue_history: str = ""
    recent_turns: tuple[str, ...] = ()
    silence_log: tuple[str, ...] = ()
    pending_user: bool = False
    # 沉默合并态：一段连续沉默只算一条，span 是从第一拍起到现在的时长
    agent_silence_sec: float = 0.0
    agent_silence_count: int = 0
    user_silence_sec: float = 0.0
    user_silence_count: int = 0
    exchange_rounds: int = 0
    source: str = "character"

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_user_text": self.last_user_text,
            "last_user_speak_at": self.last_user_speak_at,
            "last_agent_text": self.last_agent_text,
            "last_agent_speak_at": self.last_agent_speak_at,
            "dialogue_history": self.dialogue_history,
            "recent_turns": list(self.recent_turns),
            "silence_log": list(self.silence_log),
            "pending_user": self.pending_user,
            "agent_silence_sec": self.agent_silence_sec,
            "agent_silence_count": self.agent_silence_count,
            "user_silence_sec": self.user_silence_sec,
            "user_silence_count": self.user_silence_count,
            "exchange_rounds": self.exchange_rounds,
            "source": self.source,
        }

    def silence_summary_lines(self) -> list[str]:
        """沉默合并摘要：双方各至多一条，明确沉默了多久。"""
        out: list[str] = []
        if self.agent_silence_count > 0:
            n = self.agent_silence_count
            tail = f"（连续 {n} 次没有接话）" if n > 1 else "（没有接话）"
            out.append(
                f"你已沉默{_fmt_duration(self.agent_silence_sec)}{tail}。"
            )
        if self.user_silence_count > 0:
            out.append(
                f"对方已{_fmt_duration(self.user_silence_sec)}没有说话。"
            )
        return out

    def render_priority_block(self, *, now: float | None = None) -> str:
        """高优先级交互块（供编剧 WritingMaterials / 导演证据复用）。"""
        current = time.time() if now is None else float(now)
        parts: list[str] = [
            "以下是用户如何进入这场交互、以及它落在角色身上的时机；不写角色台词。"
        ]
        if self.last_user_speak_at > 0:
            parts.append(
                f"这句落在距上次对方开口 {current - float(self.last_user_speak_at):.1f} 秒的当口。"
            )
        if self.pending_user and self.last_user_text.strip():
            parts.append(
                f"对方从屏幕外发来、待角色承接：「{self.last_user_text.strip()[:300]}」"
            )
        elif self.last_user_text.strip():
            parts.append(
                f"对方从屏幕外发来：「{self.last_user_text.strip()[:300]}」"
            )
        silence_lines = self.silence_summary_lines()
        if silence_lines:
            parts.extend(silence_lines)
        if self.recent_turns:
            user_only: list[str] = []
            for raw in self.recent_turns[-8:]:
                line = _user_side_only(str(raw or "").strip())
                if line:
                    user_only.append(line)
            if user_only:
                parts.append("用户侧入站如下：\n" + "\n".join(f"- {t}" for t in user_only))
        if self.silence_log:
            parts.append(
                "沉默日志如下：\n" + "\n".join(self.silence_log[-12:])
            )
        if len(parts) == 1:
            parts.append("目前尚无交互记录。")
        return "\n".join(parts)

    def render_for_character(self, *, now: float | None = None) -> str:
        """角色本人看的往来账本：据此自然延续，不要装作没听过或没说过。"""
        current = time.time() if now is None else float(now)
        body: list[str] = []
        timing: list[str] = []
        if self.exchange_rounds > 0:
            body.append(f"你们已经往来了 {self.exchange_rounds} 轮。")
        if self.last_user_speak_at > 0:
            timing.append(
                f"对方上次说话是 {current - float(self.last_user_speak_at):.1f} 秒前"
            )
        if self.last_agent_speak_at > 0:
            timing.append(
                f"你上次开口是 {current - float(self.last_agent_speak_at):.1f} 秒前"
            )
        if timing:
            body.append("；".join(timing) + "。")
        if self.pending_user and self.last_user_text.strip():
            body.append(
                f"对方刚说、还等你接的是：「{self.last_user_text.strip()[:300]}」"
            )
        elif self.last_user_text.strip():
            body.append(
                f"对方最近一句是：「{self.last_user_text.strip()[:300]}」"
            )
        if self.last_agent_text.strip():
            body.append(
                f"你最近一句是：「{self.last_agent_text.strip()[:300]}」"
            )
        silence_lines = self.silence_summary_lines()
        if silence_lines:
            body.extend(silence_lines)
        if self.recent_turns:
            body.append(
                "已经发生的对白如下：\n"
                + "\n".join(f"- {t}" for t in self.recent_turns[-_MAX_RECENT:])
            )
        hist = self.dialogue_history.strip()
        if hist:
            body.append(f"更早的往来摘要如下：\n{hist[:1200]}")
        if not body:
            return ""
        return (
            "你们之间已经发生的往来如下。据此自然延续，"
            "不要装作没听过或没说过。\n" + "\n".join(body)
        )

    def render_plot_progress_evidence(self, *, now: float | None = None) -> str:
        """导演判断剧情卡是否消费完毕时用的交互证据。"""
        current = time.time() if now is None else float(now)
        parts: list[str] = [
            "以下是用户与角色之间的交互记录，请据此判断当前剧情卡是否已经消费完毕。"
        ]
        if self.recent_turns:
            parts.append(
                "最近对白如下：\n"
                + "\n".join(f"- {t}" for t in self.recent_turns[-8:])
            )
        if self.dialogue_history.strip():
            parts.append(
                f"工作记忆摘要如下：{self.dialogue_history.strip()[:600]}"
            )
        if self.last_user_text.strip():
            if self.pending_user:
                parts.append(
                    f"待承接的用户原话是：「{self.last_user_text.strip()[:300]}」"
                )
            else:
                parts.append(
                    f"最近一次用户原话是：「{self.last_user_text.strip()[:300]}」"
                )
        if self.last_agent_text.strip():
            parts.append(
                f"最近一次角色说法是：「{self.last_agent_text.strip()[:300]}」"
            )
        timing: list[str] = []
        if self.last_user_speak_at > 0:
            timing.append(
                f"距离上次用户发言已过去 {current - float(self.last_user_speak_at):.1f} 秒"
            )
        if self.last_agent_speak_at > 0:
            timing.append(
                f"距离上次角色发言已过去 {current - float(self.last_agent_speak_at):.1f} 秒"
            )
        if timing:
            parts.append("；".join(timing) + "。")
        silence_lines = self.silence_summary_lines()
        if silence_lines:
            parts.extend(silence_lines)
        return "\n".join(parts)


def _cache(state: Any) -> dict[str, Any]:
    store = getattr(state, "director_cache", None)
    if not isinstance(store, dict):
        return {}
    raw = store.get(_CACHE_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _write_cache(state: Any, data: dict[str, Any]) -> None:
    state.director_cache[_CACHE_KEY] = dict(data)


def _bump_silence(state: Any, key: str, *, now: float) -> None:
    """连续沉默合并：同一侧只记一段，span 从第一拍起算，count 记拍数。"""
    data = _cache(state)
    entry = data.get(key)
    if isinstance(entry, dict) and float(entry.get("since") or 0.0) > 0:
        entry["count"] = int(entry.get("count") or 1) + 1
    else:
        entry = {"since": float(now), "count": 1}
    data[key] = entry
    data["revised_at"] = now
    _write_cache(state, data)


def _clear_silence(state: Any, key: str) -> None:
    data = _cache(state)
    if key in data:
        data.pop(key, None)
        _write_cache(state, data)


def _silence_span(data: dict[str, Any], key: str, now: float) -> tuple[float, int]:
    entry = data.get(key)
    if not isinstance(entry, dict):
        return 0.0, 0
    since = float(entry.get("since") or 0.0)
    if since <= 0:
        return 0.0, 0
    return max(0.0, float(now) - since), int(entry.get("count") or 1)


def note_pending_user(
    state: Any,
    *,
    user_text: str,
    speak_at: float | None = None,
) -> None:
    """用户入站或角色开跑时：把最新用户说法记入角色侧账本。"""
    text = str(user_text or "").strip()
    if not text:
        return
    # 系统 cue 不是对方原话
    if text.startswith("（系统：") or text.startswith("(系统："):
        return
    now = time.time() if speak_at is None else float(speak_at)
    data = _cache(state)
    data["last_user_text"] = text
    data["last_user_speak_at"] = now
    data["pending_user"] = True
    data["revised_at"] = now
    turns = [
        str(x).strip()
        for x in (data.get("recent_turns") or [])
        if str(x).strip()
    ]
    # 用户开口：清掉末尾连续静默条（旧数据），写入原话
    while turns and turns[-1] == _USER_SILENCE_MARK:
        turns.pop()
    line = f"对方：{text[:300]}"
    if not turns or turns[-1] != line:
        turns.append(line)
    data["recent_turns"] = turns[-_MAX_RECENT:]
    _write_cache(state, data)
    # 用户开口即结束用户侧沉默段
    _clear_silence(state, "user_silence")
    # 与会话状态对齐，便于其它席位读到同一原话
    state.last_real_user_text = text
    state.last_user_speak_at = now


def note_user_silence_on_wake(state: Any) -> bool:
    """角色被唤醒且用户未说话：并入用户侧沉默段（合并为一条，计时长），不叠行。"""
    data = _cache(state)
    # 若刚有用户原话待承接，不记沉默
    if bool(data.get("pending_user")) and str(data.get("last_user_text") or "").strip():
        last = str(data.get("last_user_text") or "").strip()
        if last and not last.startswith("（系统："):
            return False
    _bump_silence(state, "user_silence", now=time.time())
    return True


def note_character_think_silence(
    state: Any,
    *,
    reason: str = "",
    speak_at: float | None = None,
) -> None:
    """角色本轮决策沉默：并入角色侧沉默段（合并为一条，计时长）。

    沉默不是开口：不改写 last_agent_text / last_agent_speak_at，
    「你最近一句」保留上一次真实发言。
    """
    del reason
    now = time.time() if speak_at is None else float(speak_at)
    data = _cache(state)
    # 清洗旧数据里的占位行
    turns = [
        str(x).strip()
        for x in (data.get("recent_turns") or [])
        if str(x).strip() and not _is_silence_mark(str(x))
    ]
    data["recent_turns"] = turns[-_MAX_RECENT:]
    _write_cache(state, data)
    _bump_silence(state, "agent_silence", now=now)
    data = _cache(state)
    data["pending_user"] = False
    _write_cache(state, data)


def note_character_heard_user(
    state: Any,
    *,
    user_text: str,
    turn_index: int = 0,
) -> None:
    """角色开始接用户话：确认账本上的待承接原话。"""
    del turn_index
    text = str(user_text or "").strip()
    if not text:
        return
    data = _cache(state)
    now = time.time()
    data["last_user_text"] = text
    if float(data.get("last_user_speak_at") or 0.0) <= 0:
        data["last_user_speak_at"] = float(
            getattr(state, "last_user_speak_at", 0.0) or now
        )
    data["pending_user"] = True
    data["heard_at"] = now
    data["revised_at"] = now
    _write_cache(state, data)


def _split_agent_messages(agent_text: str) -> list[str]:
    """角色的多条 speak 拆成独立消息入账本：按空行分段，段内不截断语义。"""
    raw = str(agent_text or "").strip()
    if not raw:
        return []
    pieces = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    return pieces or ([raw] if raw else [])


def note_character_exchange(
    state: Any,
    *,
    user_text: str = "",
    agent_text: str = "",
    speak_at: float | None = None,
) -> None:
    """角色可见开口后：把本轮对白写入角色侧账本。

    多条 speak 逐条入账（不 join、不截断整体），保住消息边界，
    角色下一拍才能准确记得自己说过哪几句。
    """
    now = time.time() if speak_at is None else float(speak_at)
    data = _cache(state)
    user = str(user_text or "").strip()
    if user.startswith("（系统：") or user.startswith("(系统："):
        user = ""
    agent = str(agent_text or "").strip()
    # 推理模型（MiniMax-M3 等）的 <think> 串与协议标签残片不得入账本：
    # 账本会回灌进之后每一轮的角色上下文，污染自我认知。
    agent = strip_role_tag_debris(strip_model_think(agent))
    if agent:
        data["last_agent_text"] = agent
        data["last_agent_speak_at"] = now
        state.last_agent_speak_at = now
    data["pending_user"] = False
    # 旧占位行清洗：真实对白只留原话
    turns = [
        str(x).strip()
        for x in (data.get("recent_turns") or [])
        if str(x).strip() and not _is_silence_mark(str(x))
    ]
    if user:
        data["last_user_text"] = user
        if float(data.get("last_user_speak_at") or 0.0) <= 0:
            data["last_user_speak_at"] = float(
                getattr(state, "last_user_speak_at", 0.0) or now
            )
        u_line = f"对方：{user[:300]}"
        if not turns or turns[-1] != u_line:
            turns.append(u_line)
    if agent:
        for piece in _split_agent_messages(agent):
            a_line = f"你：{piece[:300]}"
            if not turns or turns[-1] != a_line:
                turns.append(a_line)
    data["recent_turns"] = turns[-_MAX_RECENT:]
    data["revised_at"] = now
    _write_cache(state, data)
    # 真实开口即结束对应侧的沉默段
    if agent:
        _clear_silence(state, "agent_silence")
    if user:
        _clear_silence(state, "user_silence")


def export_interaction_record(
    state: Any,
    *,
    dialogue: Any | None = None,
    now: float | None = None,
) -> InteractionRecord:
    """编剧/导演向角色侧请求最新交互记录。

    合并：角色账本（优先）+ 会话状态时间戳 + distiller/snapshot 历史。
    """
    data = _cache(state)
    current = time.time() if now is None else float(now)

    last_user = str(data.get("last_user_text") or "").strip()
    if not last_user:
        last_user = str(getattr(state, "last_real_user_text", "") or "").strip()

    last_user_at = float(data.get("last_user_speak_at") or 0.0)
    if last_user_at <= 0:
        last_user_at = float(getattr(state, "last_user_speak_at", 0.0) or 0.0)

    last_agent = str(data.get("last_agent_text") or "").strip()
    last_agent_at = float(data.get("last_agent_speak_at") or 0.0)
    if last_agent_at <= 0:
        last_agent_at = float(getattr(state, "last_agent_speak_at", 0.0) or 0.0)

    pending = bool(data.get("pending_user"))
    if last_user and last_user_at > 0 and last_agent_at > 0 and last_user_at > last_agent_at:
        pending = True
    elif last_user and last_agent_at <= 0:
        pending = True

    ledger_turns = tuple(
        str(x).strip()
        for x in (data.get("recent_turns") or [])
        if str(x).strip() and not _is_silence_mark(str(x))
    )
    dialogue_history = str(data.get("dialogue_history") or "").strip()
    snapshot_turns: tuple[str, ...] = ()
    if dialogue is not None:
        wm = str(getattr(dialogue, "working_memory", "") or "").strip()
        if wm:
            dialogue_history = wm
        snapshot_turns = tuple(
            str(x).strip()
            for x in (getattr(dialogue, "recent_turns", ()) or ())
            if str(x).strip() and not _is_silence_mark(str(x))
        )

    # 角色账本与 distiller 合并：只留真实对白；沉默改为合并摘要，不再逐条交替
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(snapshot_turns) + list(ledger_turns):
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    recent = tuple(merged[-_MAX_RECENT:])

    agent_silence_sec, agent_silence_count = _silence_span(data, "agent_silence", current)
    user_silence_sec, user_silence_count = _silence_span(data, "user_silence", current)
    exchange_rounds = int(getattr(state, "interaction_exchange_count", 0) or 0)

    silence = tuple(getattr(getattr(state, "silence_log", None), "entries", ()) or ())

    return InteractionRecord(
        last_user_text=last_user,
        last_user_speak_at=last_user_at,
        last_agent_text=last_agent,
        last_agent_speak_at=last_agent_at,
        dialogue_history=dialogue_history,
        recent_turns=recent,
        silence_log=tuple(str(x) for x in silence if str(x).strip()),
        pending_user=pending,
        agent_silence_sec=agent_silence_sec,
        agent_silence_count=agent_silence_count,
        user_silence_sec=user_silence_sec,
        user_silence_count=user_silence_count,
        exchange_rounds=exchange_rounds,
        source="character",
    )


def sync_dialogue_history_into_ledger(
    state: Any,
    *,
    dialogue_history: str = "",
    recent_turns: tuple[str, ...] | list[str] | None = None,
) -> None:
    """把 distiller 摘要回写角色账本（record_dialogue 后调用）。"""
    data = _cache(state)
    hist = str(dialogue_history or "").strip()
    if hist:
        data["dialogue_history"] = hist[:2000]
    if recent_turns is not None:
        turns = [
            str(x).strip()
            for x in recent_turns
            if str(x).strip() and not _is_silence_mark(str(x))
        ]
        if turns:
            data["recent_turns"] = turns[-_MAX_RECENT:]
    data["revised_at"] = time.time()
    _write_cache(state, data)
