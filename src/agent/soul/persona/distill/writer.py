from __future__ import annotations

import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import BeliefStrength, SelfConcept
from agent.soul.voice_rules import PERSONA_DIRECTOR_RULES, YOU_VOICE_RULES

from .schema import PERSONA_DISTILL_SCHEMA_VERSION, SLICE_IDS, PersonaDistillPack


def _slice_system(task: str) -> str:
    return f"{task.strip()}\n\n{YOU_VOICE_RULES}"

_SOURCE_HEADER = "【规范化人格画像】\n{profile}\n\n【自我认知】\n{beliefs}\n\n【检索偏置关键词】\n{keywords}\n"

_SLICE_TASKS: tuple[tuple[str, str, int], ...] = (
    (
        "general",
        _slice_system("""\
你是专业的角色导演。本次请求只服务下游「通用身份名片」模块，刻画该角色稳定人设。

""" + PERSONA_DIRECTOR_RULES + """

本切片仅写「核心画像」段（你是谁、气质、价值取向）；不要写近期动态、不要写成因叙事、\
不要对话口吻示范、不要推理规则、不要记忆关键词。

输出要求：
- 自然中文，120–150 字，一段话
- 不得与源画像矛盾。只输出正文。"""),
        200,
    ),
    (
        "dialogue",
        _slice_system("""\
你是人格蒸馏系统。本次请求只服务下游「即时对话 Speak」模块。

职责边界：塑造你怎么开口、怎么对用户说话；不要复述完整六层画像，不要用「语调/句长/正式度」等字段拆解，不要 JSON、不要 markdown。

输出要求：
- 融入：身份感、说话习惯、与用户相处姿态、少说/避免什么、没把握时怎么办
- 180–220 字（含标点），一段话，语气像在对自己说明「该怎么聊」；不要条目式罗列

只输出正文。"""),
        220,
    ),
    (
        "story",
        _slice_system("""\
你是人格蒸馏系统。本次请求只服务下游「行为与叙事演化」模块。

职责边界：从经历与动机写可演化的情节化自我（背景、动机、压力反应、边界、自我叙事）；不要写对话口吻示范、不要决策推理清单、不要记忆检索词。

输出要求：
- 自然中文，250–380 字，偏叙事语气，一段话为主
- 不得与源画像矛盾

只输出正文。"""),
        380,
    ),
    (
        "reasoning",
        _slice_system("""\
你是人格蒸馏系统。本次请求只服务下游「推理与决策」模块。

职责边界：写思维方式，以及推理上的偏好与不偏好、价值取舍倾向、做判断时更倚重什么；用「更习惯…」「较少…」「倾向…」「不倾向…」表述即可。

输出要求：
- 自然中文，250–350 字，一段话，只写偏好与不偏好，不写禁止/红线/不要怎样
- 不得与源画像矛盾

只输出正文。"""),
        350,
    ),
    (
        "memory_anchor",
        _slice_system("""\
你是人格蒸馏系统。本次请求只服务下游「记忆压缩与检索锚定」模块。

职责边界：压缩你是谁、可被检索的身份与经历锚点，以及最多两条你已确立/核心的信念；不要对话口吻、不要长篇故事。

输出要求：
- 自然中文，180–260 字
- 关键词用顿号或逗号嵌入句中即可，不要单独「关键词：」工程标题

只输出正文。"""),
        260,
    ),
)


def _extract_plain_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.DOTALL)
    text = text.strip().strip('"').strip("'").strip()
    return text


def _clamp_chars(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _format_beliefs_for_prompt(concept: SelfConcept) -> str:
    lines: list[str] = []
    if concept.narrative.strip():
        lines.append(f"叙事：{concept.narrative.strip()}")
    for belief in concept.beliefs:
        if belief.strength.rank() >= BeliefStrength.established.rank():
            lines.append(f"- [{belief.strength.value}] {belief.content.strip()}")
    return "\n".join(lines)


def _build_source_block(
    profile: PersonaProfile,
    self_concept: SelfConcept,
    attention_keywords: list[str],
) -> str:
    keywords_text = "、".join(k.strip() for k in attention_keywords if k.strip())
    return _SOURCE_HEADER.format(
        profile=profile.render_catalog(),
        beliefs=_format_beliefs_for_prompt(self_concept) or "（空）",
        keywords=keywords_text or "（无）",
    )


class PersonaDistillWriter:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def _distill_slice(
        self,
        slice_id: str,
        system: str,
        max_chars: int,
        source_block: str,
    ) -> str:
        human = (
            f"{source_block}\n"
            f"【本次任务】仅蒸馏「{slice_id}」切片；其它四切片由别的请求负责，请勿涉及。\n"
            "请根据上方完整上下文输出本切片正文。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        text = _clamp_chars(_extract_plain_text(raw), max_chars)
        if not text:
            raise ValueError(f"PersonaDistillWriter: 切片 {slice_id!r} 为空")
        return text

    def distill(
        self,
        profile: PersonaProfile,
        self_concept: SelfConcept,
        *,
        attention_keywords: list[str],
        source_revision: str,
    ) -> PersonaDistillPack:
        source_block = _build_source_block(profile, self_concept, attention_keywords)
        slices: dict[str, str] = {}
        for slice_id, system, max_chars in _SLICE_TASKS:
            if slice_id not in SLICE_IDS:
                raise ValueError(f"unknown slice {slice_id!r}")
            slices[slice_id] = self._distill_slice(
                slice_id, system, max_chars, source_block
            )

        for key in SLICE_IDS:
            if key not in slices:
                raise ValueError(f"PersonaDistillWriter: 缺少切片 {key!r}")

        return PersonaDistillPack(
            schema_version=PERSONA_DISTILL_SCHEMA_VERSION,
            source_revision=source_revision,
            distilled_at=datetime.now(timezone.utc).isoformat(),
            slices=slices,
        )
