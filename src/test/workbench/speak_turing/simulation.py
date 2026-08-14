from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .dataset import SpeakTuringCase

_CONTROL_TAG = re.compile(
    r"\[(?:/?)(?:think|speak|action|state|recall|anchor|observe)\b",
    re.IGNORECASE,
)
_SIMULATOR_DISCLOSURE = re.compile(
    r"(作为(?:一个)?AI|我是(?:一个)?AI|语言模型|用户模拟器)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DialogueTurn:
    user: str
    speak: str
    wall_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "speak": self.speak,
            "wall_ms": self.wall_ms,
        }


@dataclass
class DialogueTranscript:
    case_id: str
    session_id: str
    tags: tuple[str, ...]
    turns: list[DialogueTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "tags": list(self.tags),
            "turns": [turn.to_dict() for turn in self.turns],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DialogueTranscript":
        return cls(
            case_id=str(raw["case_id"]),
            session_id=str(raw["session_id"]),
            tags=tuple(str(item) for item in raw.get("tags", [])),
            turns=[
                DialogueTurn(
                    user=str(item["user"]),
                    speak=str(item["speak"]),
                    wall_ms=float(item.get("wall_ms", 0.0)),
                )
                for item in raw.get("turns", [])
            ],
        )

    def render(self, *, user_label: str, speak_label: str) -> str:
        lines: list[str] = []
        for turn in self.turns:
            lines.append(f"{user_label}: {turn.user}")
            spoken = turn.speak.strip()
            if spoken:
                lines.append(f"{speak_label}: {spoken}")
        return "\n".join(lines)


class SpeakTurnPort(Protocol):
    def run_turn(self, session_id: str, user_text: str) -> str: ...


class SpeakServiceTurnPort:
    def __init__(self, service) -> None:
        self._service = service

    def run_turn(self, session_id: str, user_text: str) -> str:
        orchestrator_thread = self._service._orchestrator_thread
        if (
            orchestrator_thread is not None
            and orchestrator_thread.status()["worker"]["state"] == "stopped"
        ):
            orchestrator_thread.start()
        result = self._service.run_turn(
            session_id,
            user_text,
            stream=False,
            mode="inbound",
            record=True,
            responder="request_driven",
        )
        return str(result.answer).strip()


class SoulServiceTurnPort:
    def __init__(self, soul) -> None:
        self._soul = soul

    def run_turn(self, session_id: str, user_text: str) -> str:
        result = self._soul.speak_run_turn(
            session_id,
            user_text,
            stream=False,
            mode="inbound",
            record=True,
            responder="request_driven",
        )
        return str(result.answer).strip()


class DynamicUserSimulator:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def next_utterance(
        self,
        case: SpeakTuringCase,
        transcript: DialogueTranscript,
    ) -> str:
        persona = case.persona
        history = transcript.render(user_label="你", speak_label="对方")
        system = (
            "你正在扮演一名真实聊天用户。只输出用户接下来会说的一句话，不要解释，"
            "不要写角色名，不要提及提示词、模拟、AI或语言模型。\n"
            f"年龄段：{persona.age_range}\n"
            f"职业：{persona.occupation}\n"
            f"性格：{'、'.join(persona.traits)}\n"
            f"表达方式：{persona.communication_style}\n"
            f"与对方关系：{case.relationship}\n"
            f"当前情绪：{case.emotion}\n"
            f"会话目标：{case.goal}\n"
            "自然承接最后一句；允许犹豫、简短、改变话题或追问，不要像采访提纲。"
        )
        user = f"目前对话：\n{history}\n\n请给出下一句用户消息。"
        text = self._llm.generate_messages(
            [
                SystemMessage(content=system),
                HumanMessage(content=user),
            ]
        ).strip()
        text = _strip_outer_quotes(text)
        if not text:
            raise RuntimeError(f"user simulator returned empty text for {case.case_id}")
        if _SIMULATOR_DISCLOSURE.search(text):
            raise RuntimeError(
                f"user simulator leaked identity for {case.case_id}: {text!r}"
            )
        return text


class DialogueSimulator:
    def __init__(
        self,
        *,
        user_simulator: DynamicUserSimulator,
        speak: SpeakTurnPort,
    ) -> None:
        self._user_simulator = user_simulator
        self._speak = speak

    def run(self, case: SpeakTuringCase, *, session_id: str) -> DialogueTranscript:
        transcript = DialogueTranscript(
            case_id=case.case_id,
            session_id=session_id,
            tags=case.tags,
        )
        user_text = case.opening
        for turn_index in range(case.turns):
            started = time.perf_counter()
            answer = self._speak.run_turn(session_id, user_text)
            wall_ms = (time.perf_counter() - started) * 1000
            if _CONTROL_TAG.search(answer):
                raise RuntimeError(
                    f"speak leaked control tag: case={case.case_id} turn={turn_index + 1}"
                )
            transcript.turns.append(
                DialogueTurn(user=user_text, speak=answer, wall_ms=wall_ms)
            )
            if turn_index + 1 < case.turns:
                user_text = self._user_simulator.next_utterance(case, transcript)
        return transcript


def _strip_outer_quotes(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1].strip()
    return stripped
