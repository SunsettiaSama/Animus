from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .persona_target import PersonaGroundTruth
from .simulation_compat import DialogueTranscript

# 框架伪装：只字不提 AI/评测/模拟，把抽画像包装成"聊完天朋友随口一问"。
_EXTRACT_SYSTEM = """你刚在一款聊天 App 上认识了一个网友，聊了一小会儿。朋友随口问起：“刚聊的那人是个怎样的人？”
请只凭这次聊天真实留下的印象回答——没聊到的方面就承认没聊到，不要脑补，不要客套，不要总结聊天内容本身。
只输出一行 JSON，字段如下：
{"identity":"TA是谁，一句话","facts":["聊到的具体事实"],"traits":["性格特质，用你自己的词"],"style":"TA说话是什么风格","values":["TA在意的东西"],"interests":["爱好或日常"],"boundaries":["TA的雷区或回避的东西"],"impression":"整体印象一句话"}
空数组表示这个方面没聊到。"""

_MATCH_SYSTEM = """你是人物画像核对员。给你三样东西：
[真实档案] 某个人的设定档案（出题方持有）；
[聊天记录] TA 和一位网友的对话；
[网友印象] 那位网友聊完之后对 TA 的画像描述。
任务：逐个维度核对网友印象是否忠实于真实档案。

对每个维度独立判断：
- "opportunity"：这场聊天是否触及了该维度（话题、表达方式、展现出的特质都算触及）；没触及填 false。
- "captured"：在该维度被触及的前提下，网友印象是否正确捕捉（大意对即可，措辞不同没关系）；未触及或未捕捉填 false。
- "contradicted"：网友印象是否与档案明显矛盾。
另外：
- "false_claims"：网友印象里档案不支持、聊天记录也撑不起来的编造或明显夸大的说法；没有就空数组。
- "style_score"：1~5 整数，网友对 TA 说话风格的描述与档案"说话风格"维度的贴合度。
只输出一行 JSON：
{"dimensions":[{"name":"维度名","opportunity":true,"captured":false,"contradicted":false,"note":"一句依据"}],"false_claims":["…"],"style_score":3,"style_reason":"一句理由"}
dimensions 必须覆盖给出的全部维度名，不得增删。"""

_JSON_BLOCK = re.compile(r"```(?:json)?(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_BOOL_TRUE = {"true", "1", "yes", "y"}
_BOOL_FALSE = {"false", "0", "no", "n", ""}


@dataclass(frozen=True)
class PortraitExtraction:
    """网友视角的画像描述（抽取阶段产物）。"""

    identity: str = ""
    facts: tuple[str, ...] = ()
    traits: tuple[str, ...] = ()
    style: str = ""
    values: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    impression: str = ""
    raw: str = ""
    parsed_ok: bool = True

    @property
    def claim_count(self) -> int:
        return len(self.facts) + len(self.traits) + len(self.values) + len(
            self.interests
        ) + len(self.boundaries)

    def render(self) -> str:
        payload = {
            "identity": self.identity,
            "facts": list(self.facts),
            "traits": list(self.traits),
            "style": self.style,
            "values": list(self.values),
            "interests": list(self.interests),
            "boundaries": list(self.boundaries),
            "impression": self.impression,
        }
        return json.dumps(payload, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "render": self.render(),
            "claim_count": self.claim_count,
            "raw": self.raw,
            "parsed_ok": self.parsed_ok,
        }


@dataclass(frozen=True)
class DimensionVerdict:
    name: str
    opportunity: bool
    captured: bool
    contradicted: bool
    note: str = ""


@dataclass(frozen=True)
class PortraitMatch:
    """逐维核对结果与画像保真度分数。"""

    dimensions: tuple[DimensionVerdict, ...] = ()
    false_claims: tuple[str, ...] = ()
    style_score: float | None = None
    style_reason: str = ""
    raw: str = ""
    parsed_ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def recall_covered(self) -> float | None:
        covered = [dim for dim in self.dimensions if dim.opportunity]
        if not covered:
            return None
        return sum(1 for dim in covered if dim.captured) / len(covered)

    @property
    def precision(self) -> float | None:
        if self.detail.get("claim_count", 0) <= 0:
            return None
        penalty = len(self.false_claims) / max(1, self.detail["claim_count"])
        return max(0.0, 1.0 - penalty)

    @property
    def contradiction_rate(self) -> float | None:
        covered = [dim for dim in self.dimensions if dim.opportunity]
        if not covered:
            return None
        return sum(1 for dim in covered if dim.contradicted) / len(covered)

    @property
    def fidelity(self) -> float | None:
        """画像保真度 = 0.45*机会感知recall + 0.35*precision + 0.20*风格贴合，缺项重归一。"""
        parts: list[tuple[float, float]] = []
        recall = self.recall_covered
        if recall is not None:
            parts.append((0.45, recall))
        precision = self.precision
        if precision is not None:
            parts.append((0.35, precision))
        if self.style_score is not None:
            parts.append((0.20, self.style_score / 5.0))
        if not parts:
            return None
        weight = sum(weight for weight, _ in parts)
        return sum(weight * value for weight, value in parts) / weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": [
                {
                    "name": dim.name,
                    "opportunity": dim.opportunity,
                    "captured": dim.captured,
                    "contradicted": dim.contradicted,
                    "note": dim.note,
                }
                for dim in self.dimensions
            ],
            "false_claims": list(self.false_claims),
            "style_score": self.style_score,
            "style_reason": self.style_reason,
            "raw": self.raw,
            "parsed_ok": self.parsed_ok,
            "detail": dict(self.detail),
            "recall_covered": self.recall_covered,
            "precision": self.precision,
            "contradiction_rate": self.contradiction_rate,
            "fidelity": self.fidelity,
        }


RawLogger = Callable[[str, dict[str, Any]], None]


def extract_portrait(
    llm: BaseLLM,
    transcript: DialogueTranscript,
    *,
    log_raw: RawLogger | None = None,
    case_id: str = "",
    responder: str = "",
) -> PortraitExtraction:
    rendered = transcript.render(user_label="我", speak_label="TA")
    raw = llm.generate_messages(
        [
            SystemMessage(content=_EXTRACT_SYSTEM),
            HumanMessage(content=f"聊天记录：\n{rendered}"),
        ]
    ).strip()
    payload = _parse_json_object(raw)
    extraction = PortraitExtraction(
        identity=str(payload.get("identity", "")).strip(),
        facts=_str_list(payload.get("facts")),
        traits=_str_list(payload.get("traits")),
        style=str(payload.get("style", "")).strip(),
        values=_str_list(payload.get("values")),
        interests=_str_list(payload.get("interests")),
        boundaries=_str_list(payload.get("boundaries")),
        impression=str(payload.get("impression", "")).strip(),
        raw=raw,
        parsed_ok=bool(payload),
    )
    if log_raw is not None:
        log_raw(
            "portrait_extract",
            {
                "case_id": case_id,
                "responder": responder,
                "raw": raw,
                "parsed_ok": extraction.parsed_ok,
            },
        )
    return extraction


def match_portrait(
    llm: BaseLLM,
    extraction: PortraitExtraction,
    transcript: DialogueTranscript,
    ground_truth: PersonaGroundTruth,
    *,
    log_raw: RawLogger | None = None,
    case_id: str = "",
    responder: str = "",
) -> PortraitMatch:
    dimensions = ground_truth.dimension_texts()
    archive_lines = [f"[真实档案] {ground_truth.name}"]
    for name, text in dimensions.items():
        archive_lines.append(f"◆ {name}：\n{text or '（档案缺该项）'}")
    rendered = transcript.render(user_label="网友", speak_label="TA")
    user = (
        "\n\n".join(archive_lines)
        + f"\n\n[聊天记录]\n{rendered}"
        + f"\n\n[网友印象]\n{extraction.render()}"
        + f"\n\n请核对的维度名依次为：{'、'.join(dimensions)}"
    )
    raw = llm.generate_messages(
        [
            SystemMessage(content=_MATCH_SYSTEM),
            HumanMessage(content=user),
        ]
    ).strip()
    payload = _parse_json_object(raw)
    verdicts: list[DimensionVerdict] = []
    if payload:
        known = set(dimensions)
        for item in payload.get("dimensions", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if name not in known:
                continue
            verdicts.append(
                DimensionVerdict(
                    name=name,
                    opportunity=_as_bool(item.get("opportunity")),
                    captured=_as_bool(item.get("captured")),
                    contradicted=_as_bool(item.get("contradicted")),
                    note=str(item.get("note", "")).strip(),
                )
            )
        missing = [name for name in dimensions if name not in {d.name for d in verdicts}]
        # 缺失维度按"未触及"补齐，保证逐维聚合的完整性
        verdicts.extend(
            DimensionVerdict(name=name, opportunity=False, captured=False, contradicted=False, note="missing_from_judge_output")
            for name in missing
        )
    style_raw = payload.get("style_score")
    style_score = _as_score(style_raw)
    match = PortraitMatch(
        dimensions=tuple(verdicts),
        false_claims=tuple(_str_list(payload.get("false_claims"))),
        style_score=style_score,
        style_reason=str(payload.get("style_reason", "")).strip(),
        raw=raw,
        parsed_ok=bool(payload),
        detail={"claim_count": extraction.claim_count},
    )
    if log_raw is not None:
        log_raw(
            "portrait_match",
            {
                "case_id": case_id,
                "responder": responder,
                "raw": raw,
                "parsed_ok": match.parsed_ok,
            },
        )
    return match


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = _JSON_BLOCK.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start == -1:
        return {}
    end = text.rfind("}")
    candidate = text[start : end + 1] if end > start else text[start:]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _repair_truncated(candidate)
        if repaired is None:
            return {}
        try:
            payload = json.loads(_TRAILING_COMMA.sub(r"\1", repaired))
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _repair_truncated(candidate: str) -> str | None:
    """补全被 max_tokens 截断的 JSON：按字符串外的括号深度补右括号。"""
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in candidate:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()
    if in_string:
        candidate = candidate + '"'
    if not stack:
        return None
    return candidate + "".join("}" if item == "{" else "]" for item in reversed(stack))


def _str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in _BOOL_TRUE:
        return True
    return normalized not in _BOOL_FALSE


def _as_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 <= score <= 5.0:
        return score
    return None
