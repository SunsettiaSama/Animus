from __future__ import annotations

import os
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
from .types import EnterGreetingDecision, EnterGreetingProbe, EnterGreetingTurnSpec

EnterGreetingHandler = Callable[[EnterGreetingTurnSpec], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def render_enter_greeting_decision_system() -> str:
    think = speak_tag("think")
    greet = speak_tag("state", "greet")
    hold = speak_tag("state", "hold")
    lines = [
        "【进入会话判定】（仅内部决策，不对用户展示）",
        "",
        "背景：用户刚进入对话窗口，尚未发言。",
        "任务：判断是否适合主动用一句极短的话头打破空白。",
        "",
        "输出要求：",
        f"- 必须写 {think}：理由（简短）",
        f"- 若适合开口：写 {greet}，并在 think 末行给出「角度：…」",
        f"- 若不宜开口：写 {hold}",
        "- 不要写 speak、action 等对用户可见内容",
    ]
    return "\n".join(lines)


def render_enter_greeting_decision_user(probe: EnterGreetingProbe) -> str:
    return (
        f"用户进入会话已约 {int(probe.elapsed_sec)} 秒，尚未发送消息。"
        "请判定是否要主动挑起话头。"
    )


_ANGLE_PATTERN = re.compile(r"角度[：:]\s*(.+)", re.MULTILINE)


def parse_enter_greeting_decision(raw: str) -> EnterGreetingDecision:
    thinks: list[str] = []
    should_greet = False
    angle = ""
    for block in iter_tag_blocks(raw):
        if block.kind == "think" and block.content:
            thinks.append(block.content)
        elif block.kind == "state" and block.content:
            state = block.content.strip().lower()
            if state == "greet":
                should_greet = True
            elif state == "hold":
                should_greet = False
    thought = "\n".join(thinks).strip()
    if thought:
        match = _ANGLE_PATTERN.search(thought)
        if match is not None:
            angle = match.group(1).strip()
    if should_greet and not angle and thought:
        angle = thought.split("\n")[-1].strip()[:120]
    return EnterGreetingDecision(
        should_greet=should_greet,
        thought=thought,
        angle=angle,
        raw=raw,
    )


@dataclass
class _EnterGreetingState:
    armed_at: datetime = field(default_factory=_utcnow)
    timer: threading.Timer | None = None
    fired: bool = False


@dataclass
class EnterGreetingManager:
    registry: SpeakSessionRegistry
    delay_sec: float = field(
        default_factory=lambda: _env_float("REACT_SPEAK_ENTER_GREETING_SEC", 60.0),
    )
    dialogue_supplier: Callable[[str], str] | None = None
    is_pushing: Callable[[str], bool] | None = None
    _states: dict[str, _EnterGreetingState] = field(default_factory=dict)
    _armed: dict[str, EnterGreetingTurnSpec] = field(default_factory=dict)
    _handler: EnterGreetingHandler | None = None
    _now_fn: Callable[[], datetime] = field(default_factory=lambda: _utcnow)
    _worker: DomainWorker = field(default_factory=lambda: DomainWorker("speak-enter-greeting-worker"))
    _llm: SpeakLLMEngine | None = None

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        state = self._states.pop(sid, None)
        if state is not None and state.timer is not None:
            state.timer.cancel()
        self._armed.pop(sid, None)

    def cancel_session(self, session_id: str) -> None:
        self.clear_session(session_id)

    def set_greeting_handler(self, handler: EnterGreetingHandler | None) -> None:
        self._handler = handler

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def start_worker(self) -> None:
        self._worker.start()

    def stop_worker(self) -> None:
        self._worker.stop()

    def pop_armed_turn(self, session_id: str) -> EnterGreetingTurnSpec | None:
        return self._armed.pop(session_id.strip(), None)

    def arm_turn(self, spec: EnterGreetingTurnSpec) -> None:
        self._armed[spec.session_id.strip()] = spec

    def on_user_message(self, session_id: str) -> None:
        self.cancel_session(session_id)

    def arm_session(self, session_id: str) -> None:
        sid = session_id.strip()
        if not sid:
            return
        state = self._states.get(sid)
        if state is not None and state.timer is not None:
            state.timer.cancel()
        state = _EnterGreetingState(armed_at=self._now_fn())
        self._states[sid] = state
        delay = max(1.0, float(self.delay_sec))

        def _fire() -> None:
            self._worker.enqueue(lambda: self._evaluate_and_maybe_fire(sid))

        state.timer = threading.Timer(delay, _fire)
        state.timer.daemon = True
        state.timer.start()

    def _evaluate_and_maybe_fire(self, session_id: str) -> None:
        sid = session_id.strip()
        state = self._states.get(sid)
        if state is None or state.fired:
            return
        if self.is_pushing is not None and self.is_pushing(sid):
            return
        if self._llm is None or self._handler is None:
            return
        elapsed = (self._now_fn() - state.armed_at).total_seconds()
        dialogue = ""
        if self.dialogue_supplier is not None:
            dialogue = self.dialogue_supplier(sid)
        probe = EnterGreetingProbe(
            session_id=sid,
            elapsed_sec=elapsed,
            turn_index=self.registry.current_turn_index(sid),
            dialogue_compressed=dialogue,
        )
        raw = self._llm.generate(
            render_enter_greeting_decision_user(probe),
            system=render_enter_greeting_decision_system(),
        ).text
        decision = parse_enter_greeting_decision(raw)
        state.fired = True
        if not decision.should_greet:
            return
        spec = EnterGreetingTurnSpec(
            session_id=sid,
            elapsed_sec=elapsed,
            angle=decision.angle,
            thought=decision.thought,
            dialogue_compressed=dialogue,
        )
        self._handler(spec)
