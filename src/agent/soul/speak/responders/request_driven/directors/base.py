from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from infra.llm import BaseLLM

from agent.soul.speak.llm.engine import SpeakLLMEngine

from ..orchestrator.prompt_trace import get_prompt_trace
from ..orchestrator.state.core.enums import normalize_continuity
from ..orchestrator.state.core.delivery import DeliveryPlan, ReplySegment, build_delivery_plan
from ..orchestrator.state.core.types import SessionSnapshot

logger = logging.getLogger(__name__)


# 全体导演共用口吻：指导角色过这一拍；不写台词。
DIRECTOR_VOICE = (
    "你是导演，指导角色，不代替角色说话。"
    "对方在远程通过文字与角色通信，不在她身边；这个端口是她对外发短消息的渠道。"
    "角色对外只写 <speak>，每次一条短消息。"
    "这一拍手头的动作、过渡和姿态，需要由你写具体，形成一个连续过程——包括手头细节、内心倾向、过渡和姿态，并写入现实时间轴。"
    "动作不能留空，也不能让角色自己编，否则她会凭空编造。"
    "代入此刻：这个人下一条短消息会说什么？"
    "你只写处境，不写角色台词，也不用第一人称「我」去演角色；台词由角色 agent 负责。"
)

@dataclass
class DirectorOutput:
    director: str
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    used_fallback: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "director": self.director,
            "payload": dict(self.payload),
            "reason": self.reason,
            "used_fallback": self.used_fallback,
        }


class DirectorLLMCaller:
    """导演专用低时延 LLM 调用器。"""

    def __init__(
        self,
        *,
        llm: BaseLLM | None = None,
        timeout_sec: float = 8.0,
        max_concurrent: int = 4,
    ) -> None:
        self._engine = SpeakLLMEngine(llm=llm)
        self._timeout_sec = timeout_sec
        self._max_concurrent = max_concurrent
        self._gate = threading.BoundedSemaphore(max(1, max_concurrent))

    @property
    def available(self) -> bool:
        return self._engine.llm is not None

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        session_id: str = "",
        director: str = "",
        turn_index: int | None = None,
    ) -> str:
        sid = session_id.strip()
        if not self.available:
            if sid:
                get_prompt_trace().emit_event(
                    sid,
                    label="director_llm_unavailable",
                    turn_index=turn_index,
                    payload={
                        "director": director,
                        "system": system,
                        "user": user,
                    },
                )
            return ""
        with self._gate:
            logger.info(
                "[director_llm] start director=%s session=%s turn=%s",
                director or "unknown",
                sid or "-",
                turn_index,
            )
            raw = self._engine.generate(user, system=system).text.strip()
        if sid:
            get_prompt_trace().emit_submodule_llm(
                sid,
                submodule=f"director.{director or 'unknown'}",
                system=system,
                user=user,
                response_preview=raw,
            )
            logger.info(
                "[director_llm] done director=%s session=%s chars=%d preview=%r",
                director or "unknown",
                sid,
                len(raw),
                raw[:160],
            )
        return raw


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    blob = _first_json_object(text)
    if not blob:
        return {}
    decoder = json.JSONDecoder()
    try:
        payload, _end = decoder.raw_decode(blob)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def clamp_wait_ms(value: Any, *, emotional: bool = False) -> int:
    parsed = int(value or 0)
    if parsed <= 0:
        return 0
    if emotional:
        return max(120, min(4200, parsed))
    return max(120, min(2800, parsed))


def parse_delivery_plan_payload(
    payload: dict[str, Any],
    *,
    turn_index: int = 0,
    plan_id: str = "",
) -> DeliveryPlan:
    segments_raw = payload.get("segments") or []
    segments: list[ReplySegment] = []
    if isinstance(segments_raw, list):
        for item in segments_raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            wait_ms = clamp_wait_ms(
                item.get("wait_ms", 0),
                emotional=bool(item.get("emotional", False)),
            )
            wait_reason = str(item.get("wait_reason", "")).strip()
            continuity = normalize_continuity(str(item.get("continuity", "finish")))
            segments.append(
                ReplySegment(
                    text=text,
                    wait_ms=wait_ms,
                    wait_reason=wait_reason,
                    continuity=continuity,
                ),
            )
    continuity = normalize_continuity(str(payload.get("continuity", "finish")))
    sample = str(payload.get("sample_narration", "")).strip()
    return build_delivery_plan(
        segments=segments,
        continuity=continuity,
        sample_narration=sample,
        plan_id=plan_id,
        turn_index=turn_index,
    )


class BaseDirector(Protocol):
    name: str

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput: ...
