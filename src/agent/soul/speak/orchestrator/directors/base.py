from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from infra.llm import BaseLLM

from agent.soul.speak.llm.engine import SpeakLLMEngine

from ..prompt_trace import get_prompt_trace
from ..state.core.enums import normalize_continuity
from ..state.core.delivery import DeliveryPlan, ReplySegment, build_delivery_plan
from ..state.core.types import SessionSnapshot


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
            raw = self._engine.generate(user, system=system).text.strip()
        if sid:
            get_prompt_trace().emit_submodule_llm(
                sid,
                submodule=f"director.{director or 'unknown'}",
                system=system,
                user=user,
                response_preview=raw,
            )
        return raw


def extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    payload = json.loads(match.group())
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
