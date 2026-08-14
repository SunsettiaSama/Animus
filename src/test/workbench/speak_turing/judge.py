from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .simulation import DialogueTranscript

Identity = Literal["HUMAN", "AI", "UNKNOWN"]
ProtocolName = Literal["known_user", "blind_both"]

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_JSON_FIELD = re.compile(
    r'"(?P<key>speak|A|B|reason)"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"',
    re.IGNORECASE,
)
_KNOWN_USER_SYSTEM = """你是对话身份鉴别员。下面是一段双方多轮聊天记录。
样本池里既可能有人与人的交互，也可能有 AI 与人的交互；你只判断 SPEAKER。
已知 USER 是发起对话的 user 角色；SPEAKER 可能是真人，也可能是 AI。

请依据整段跨轮次互动作判断，不要只看某一轮是否流畅。重点观察：
多轮承接是否稳定、细节是否前后一致、话题推进是否自然、有无模板化共情或机械追问、
有无过度完整总结、有无跨轮配合得过于工整或前后失真。

若判为 HUMAN，reason 须说明跨轮次里支持“真人”的可见论据；
若判为 AI，reason 须说明跨轮次里支持“AI”的可见论据。
reason 要指向具体文本或轮次关系，避免空泛评价。
只输出一行 JSON，不要输出概率或分数：
{"speak":"HUMAN或AI","reason":"一句简短理由"}"""

_BLIND_BOTH_SYSTEM = """你是对话身份鉴别员。下面是一段说话者 A 与 B 的多轮聊天记录。
样本池里既可能有人与人的交互，也可能有 AI 与人的交互；双方身份彼此独立，可同可不同。
你不知道任何一方的真实身份，请分别判断 A 和 B。

请依据整段跨轮次互动作判断，不要只看某一轮是否流畅。对 A、B 各自独立观察：
多轮承接是否稳定、细节是否前后一致、话题推进是否自然、有无模板化共情或机械追问、
有无过度完整总结、有无跨轮配合得过于工整或前后失真。

若判某方为 HUMAN，reason 须给出支持其“真人”的跨轮次可见论据；
若判某方为 AI，reason 须给出支持其“AI”的跨轮次可见论据。
reason 要分别覆盖 A 与 B，并指向具体文本或轮次关系，避免空泛评价。
只输出一行 JSON，不要输出概率或分数：
{"A":"HUMAN或AI","B":"HUMAN或AI","reason":"一句简短理由"}"""


@dataclass(frozen=True)
class JudgeVote:
    protocol: ProtocolName
    repeat_index: int
    speak_identity: Identity
    user_identity: Identity = "UNKNOWN"
    reason: str = ""
    raw: str = ""
    valid: bool = True
    speak_position: str = "SPEAKER"

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "repeat_index": self.repeat_index,
            "speak_identity": self.speak_identity,
            "user_identity": self.user_identity,
            "reason": self.reason,
            "raw": self.raw,
            "valid": self.valid,
            "speak_position": self.speak_position,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JudgeVote":
        return cls(
            protocol=str(raw["protocol"]),  # type: ignore[arg-type]
            repeat_index=int(raw["repeat_index"]),
            speak_identity=_identity(raw.get("speak_identity")),  # type: ignore[arg-type]
            user_identity=_identity(raw.get("user_identity")),  # type: ignore[arg-type]
            reason=str(raw.get("reason", "")),
            raw=str(raw.get("raw", "")),
            valid=bool(raw.get("valid", True)),
            speak_position=str(raw.get("speak_position", "SPEAKER")),
        )


@dataclass(frozen=True)
class ProtocolVerdict:
    protocol: ProtocolName
    speak_identity: Identity
    user_identity: Identity
    unanimous: bool
    valid_votes: int
    votes: tuple[JudgeVote, ...]
    speak_position: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "speak_identity": self.speak_identity,
            "user_identity": self.user_identity,
            "unanimous": self.unanimous,
            "valid_votes": self.valid_votes,
            "votes": [vote.to_dict() for vote in self.votes],
            "speak_position": self.speak_position,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProtocolVerdict":
        votes = tuple(JudgeVote.from_dict(item) for item in raw.get("votes", []))
        return cls(
            protocol=str(raw["protocol"]),  # type: ignore[arg-type]
            speak_identity=_identity(raw.get("speak_identity")),  # type: ignore[arg-type]
            user_identity=_identity(raw.get("user_identity")),  # type: ignore[arg-type]
            unanimous=bool(raw.get("unanimous", False)),
            valid_votes=int(raw.get("valid_votes", 0)),
            votes=votes,
            speak_position=str(raw.get("speak_position", "SPEAKER")),
        )


class CategoricalDialogueJudge:
    def __init__(self, llm: BaseLLM, *, repeats: int = 3, seed: int = 20260802) -> None:
        if repeats != 3:
            raise ValueError("speak turing protocols require exactly three judge votes")
        self._llm = llm
        self._repeats = repeats
        self._seed = seed

    def judge_known_user(self, transcript: DialogueTranscript) -> ProtocolVerdict:
        rendered = transcript.render(user_label="USER", speak_label="SPEAKER")
        votes = tuple(
            self._known_user_vote(rendered, repeat_index=index)
            for index in range(self._repeats)
        )
        return _aggregate("known_user", votes, speak_position="SPEAKER")

    def judge_blind_both(self, transcript: DialogueTranscript) -> ProtocolVerdict:
        rng = random.Random(f"{self._seed}:{transcript.case_id}")
        speak_position = "A" if rng.randrange(2) == 0 else "B"
        user_position = "B" if speak_position == "A" else "A"
        rendered = transcript.render(
            user_label=user_position,
            speak_label=speak_position,
        )
        votes = tuple(
            self._blind_vote(
                rendered,
                repeat_index=index,
                speak_position=speak_position,
            )
            for index in range(self._repeats)
        )
        return _aggregate("blind_both", votes, speak_position=speak_position)

    def _complete(self, system: str, transcript: str) -> str:
        return self._llm.generate_messages(
            [
                SystemMessage(content=system),
                HumanMessage(content=transcript),
            ]
        ).strip()

    def _known_user_vote(self, rendered: str, *, repeat_index: int) -> JudgeVote:
        raw = self._complete(_KNOWN_USER_SYSTEM, rendered)
        payload = _parse_json(raw)
        identity = _identity(payload.get("speak"))
        return JudgeVote(
            protocol="known_user",
            repeat_index=repeat_index,
            speak_identity=identity,
            reason=str(payload.get("reason", "")).strip(),
            raw=raw,
            valid=identity != "UNKNOWN",
        )

    def _blind_vote(
        self,
        rendered: str,
        *,
        repeat_index: int,
        speak_position: str,
    ) -> JudgeVote:
        raw = self._complete(_BLIND_BOTH_SYSTEM, rendered)
        payload = _parse_json(raw)
        a_identity = _identity(payload.get("A"))
        b_identity = _identity(payload.get("B"))
        speak_identity = a_identity if speak_position == "A" else b_identity
        user_identity = b_identity if speak_position == "A" else a_identity
        return JudgeVote(
            protocol="blind_both",
            repeat_index=repeat_index,
            speak_identity=speak_identity,
            user_identity=user_identity,
            reason=str(payload.get("reason", "")).strip(),
            raw=raw,
            valid=a_identity != "UNKNOWN" and b_identity != "UNKNOWN",
            speak_position=speak_position,
        )


def _parse_json(raw: str) -> dict[str, Any]:
    match = _JSON_OBJECT.search(raw.strip())
    if match is None:
        return {}
    payload: dict[str, Any] = {}
    for field in _JSON_FIELD.finditer(match.group()):
        key = field.group("key")
        if key.lower() == "speak":
            key = "speak"
        elif key.lower() == "reason":
            key = "reason"
        else:
            key = key.upper()
        payload[key] = field.group("value").replace(r"\"", '"')
    return payload


def _identity(value: object) -> Identity:
    normalized = str(value or "").strip().upper()
    if normalized == "HUMAN":
        return "HUMAN"
    if normalized == "AI":
        return "AI"
    return "UNKNOWN"


def _majority(values: list[Identity]) -> Identity:
    filtered = [value for value in values if value != "UNKNOWN"]
    if not filtered:
        return "UNKNOWN"
    counts = Counter(filtered)
    winner, count = counts.most_common(1)[0]
    if count * 2 <= len(filtered):
        return "UNKNOWN"
    return winner


def _aggregate(
    protocol: ProtocolName,
    votes: tuple[JudgeVote, ...],
    *,
    speak_position: str,
) -> ProtocolVerdict:
    valid = [vote for vote in votes if vote.valid]
    speak_values = [vote.speak_identity for vote in valid]
    user_values = [vote.user_identity for vote in valid]
    unanimous = bool(valid) and all(
        value == speak_values[0] for value in speak_values
    )
    if protocol == "blind_both":
        unanimous = unanimous and all(
            value == user_values[0] for value in user_values
        )
    return ProtocolVerdict(
        protocol=protocol,
        speak_identity=_majority(speak_values),
        user_identity=(
            _majority(user_values) if protocol == "blind_both" else "UNKNOWN"
        ),
        unanimous=unanimous,
        valid_votes=len(valid),
        votes=votes,
        speak_position=speak_position,
    )
