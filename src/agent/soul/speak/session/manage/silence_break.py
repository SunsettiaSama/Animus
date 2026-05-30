from __future__ import annotations

import os
import random
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.speak.io.outbound.stream.protocol.tags import speak_tag
from agent.soul.speak.io.outbound.stream.parse.tags import iter_tag_blocks
from agent.soul.workers import DomainWorker

from ...llm.engine import SpeakLLMEngine
from ..lifecycle.hold.registry import SpeakSessionRegistry
from .types import (
    SilenceBreakDecision,
    SilenceBreakProbe,
    SilenceBreakTurnSpec,
)

SilenceBreakHandler = Callable[[SilenceBreakTurnSpec], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def render_silence_decision_system() -> str:
    think = speak_tag("think")
    break_state = speak_tag("state", "break_silence")
    hold = speak_tag("state", "hold")
    lines = [
        "【静默判定】（仅内部决策，不对用户展示）",
        "",
        "背景：对话中用户在一段时间内未再发消息。",
        "任务：结合上下文揣摩用户可能在想什么、是否在忙；判断你是否适合用一句极短对白打破沉默。",
        "",
        "输出要求：",
        f"- 必须写 {think}：揣摩与理由（简短）",
        f"- 若适合轻问/承接：写 {break_state}，并在 think 末行给出「角度：…」（一句话）",
        f"- 若不宜开口：写 {hold}",
        "- 不要写 speak、action 等对用户可见内容",
    ]
    return "\n".join(lines)


def render_silence_decision_user(probe: SilenceBreakProbe) -> str:
    lines = [
        f"用户已静默约 {int(probe.elapsed_sec)} 秒（turn_index={probe.turn_index}）。",
        "请判定是否要打破沉默。",
    ]
    if probe.dialogue_compressed.strip():
        lines.append("近期对话摘要：\n" + probe.dialogue_compressed.strip())
    return "\n".join(lines)


_ANGLE_PATTERN = re.compile(r"角度[：:]\s*(.+)", re.MULTILINE)


def parse_silence_decision(raw: str) -> SilenceBreakDecision:
    thinks: list[str] = []
    should_break = False
    angle = ""
    for block in iter_tag_blocks(raw):
        if block.kind == "think" and block.content:
            thinks.append(block.content)
        elif block.kind == "state" and block.content:
            state = block.content.strip().lower()
            if state in ("break_silence", "break"):
                should_break = True
            elif state == "hold":
                should_break = False
    thought = "\n".join(thinks).strip()
    if thought:
        match = _ANGLE_PATTERN.search(thought)
        if match is not None:
            angle = match.group(1).strip()
    if should_break and not angle and thought:
        angle = thought.split("\n")[-1].strip()[:120]
    return SilenceBreakDecision(
        should_break=should_break,
        thought=thought,
        angle=angle,
        raw=raw,
    )


@dataclass
class _SilenceState:
    last_user_at: datetime = field(default_factory=_utcnow)
    last_agent_at: datetime = field(default_factory=_utcnow)
    timer: threading.Timer | None = None
    breaks_this_generation: int = 0
    generation: int = 1


@dataclass
class SilenceBreakManager:
    """长时间静默后：随机探测 + LLM 语义判定，决定是否打破沉默。

    补位式弱社交，非话题引导；TODO: 与 presence expectation 主动开聊统一为
    agent 引导型主动提问管线。
    """

    registry: SpeakSessionRegistry
    silence_sec: float = field(default_factory=lambda: _env_float("REACT_SPEAK_SILENCE_BREAK_SEC", 90.0))
    base_probability: float = field(
        default_factory=lambda: _env_float("REACT_SPEAK_SILENCE_BREAK_BASE_PROB", 0.22),
    )
    max_breaks_per_generation: int = field(
        default_factory=lambda: _env_int("REACT_SPEAK_SILENCE_BREAK_MAX", 3),
    )
    dialogue_supplier: Callable[[str], str] | None = None
    is_active: Callable[[str], bool] | None = None
    is_pushing: Callable[[str], bool] | None = None
    _states: dict[str, _SilenceState] = field(default_factory=dict)
    _armed: dict[str, SilenceBreakTurnSpec] = field(default_factory=dict)
    _handler: SilenceBreakHandler | None = None
    _rng: Callable[[], float] = field(default_factory=lambda: random.random)
    _now_fn: Callable[[], datetime] = field(default_factory=lambda: _utcnow)
    _worker: DomainWorker = field(default_factory=lambda: DomainWorker("speak-silence-break-worker"))
    _llm: SpeakLLMEngine | None = None

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        state = self._states.pop(sid, None)
        if state is not None and state.timer is not None:
            state.timer.cancel()
        self._armed.pop(sid, None)

    def set_break_handler(self, handler: SilenceBreakHandler | None) -> None:
        self._handler = handler

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def start_worker(self) -> None:
        self._worker.start()

    def stop_worker(self) -> None:
        self._worker.stop()

    def pop_armed_turn(self, session_id: str) -> SilenceBreakTurnSpec | None:
        return self._armed.pop(session_id.strip(), None)

    def arm_turn(self, spec: SilenceBreakTurnSpec) -> None:
        self._armed[spec.session_id.strip()] = spec

    def on_user_message(self, session_id: str) -> None:
        sid = session_id.strip()
        state = self._state(sid)
        now = self._now_fn()
        state.last_user_at = now
        self._armed.pop(sid, None)
        self._cancel_timer(state)

    def on_agent_turn_complete(self, session_id: str) -> None:
        sid = session_id.strip()
        record = self.registry.get(sid)
        state = self._state(sid)
        if state.generation != record.generation:
            state.generation = record.generation
            state.breaks_this_generation = 0
        now = self._now_fn()
        state.last_agent_at = now
        self._cancel_timer(state)
        self._schedule_timer(sid, state)

    def _state(self, session_id: str) -> _SilenceState:
        sid = session_id.strip()
        if sid not in self._states:
            self._states[sid] = _SilenceState()
        return self._states[sid]

    def _cancel_timer(self, state: _SilenceState) -> None:
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None

    def _schedule_timer(self, session_id: str, state: _SilenceState) -> None:
        delay = max(1.0, float(self.silence_sec))

        def _fire() -> None:
            self._worker.enqueue(lambda: self._on_timer(session_id))

        timer = threading.Timer(delay, _fire)
        timer.daemon = True
        state.timer = timer
        timer.start()

    def _on_timer(self, session_id: str) -> None:
        sid = session_id.strip()
        state = self._states.get(sid)
        if state is None:
            return
        state.timer = None
        if self.is_active is not None and not self.is_active(sid):
            return
        if self.is_pushing is not None and self.is_pushing(sid):
            return
        if state.breaks_this_generation >= self.max_breaks_per_generation:
            return

        now = self._now_fn()
        elapsed = (now - state.last_agent_at).total_seconds()
        if elapsed < self.silence_sec * 0.85:
            return
        if (now - state.last_user_at).total_seconds() < self.silence_sec * 0.85:
            return

        roll = self._rng()
        extra = min(0.55, max(0.0, (elapsed - self.silence_sec) / max(self.silence_sec, 1.0) * 0.35))
        threshold = min(0.88, self.base_probability + extra)
        if roll > threshold:
            return

        dialogue = ""
        if self.dialogue_supplier is not None:
            dialogue = self.dialogue_supplier(sid).strip()
        turn_index = self.registry.current_turn_index(sid)
        probe = SilenceBreakProbe(
            session_id=sid,
            elapsed_sec=elapsed,
            turn_index=turn_index,
            dialogue_compressed=dialogue,
            roll=roll,
            threshold=threshold,
        )
        decision = self._decide(probe)
        if not decision.should_break:
            return

        spec = SilenceBreakTurnSpec(
            session_id=sid,
            elapsed_sec=elapsed,
            angle=decision.angle,
            thought=decision.thought,
            dialogue_compressed=dialogue,
        )
        state.breaks_this_generation += 1
        handler = self._handler
        if handler is not None:
            handler(spec)

    def _decide(self, probe: SilenceBreakProbe) -> SilenceBreakDecision:
        llm = self._llm
        if llm is None or llm.llm is None:
            return SilenceBreakDecision(should_break=False, thought="llm unavailable")
        if self._worker.status()["state"] != "running":
            return SilenceBreakDecision(should_break=False, thought="worker stopped")

        system = render_silence_decision_system()
        user = render_silence_decision_user(probe)
        raw = llm.generate(user, system=system).text
        return parse_silence_decision(raw)
