"""回复组装：人设 + 检索到的记忆参考 + 历史 + 当前输入。"""
from __future__ import annotations

from .schema import AGENT_NAME, PERSONA_TEXT, HumanenessCase

_INSTRUCTION = (
    "下面的「相关记忆」段落是你能想起来的东西；与当前话题无关的部分可以自然忽略，"
    "绝不编造记忆里没有的事。想不起来就说想不起来，像真人一样坦白。"
    "回复要像真人聊天：口语、简短（一般不超过三句话）、可以有语气词和犹豫，"
    "不打官腔、不用列举、不做总结陈词。"
)


def compose_system(case: HumanenessCase, memory_block_text: str) -> str:
    parts = [PERSONA_TEXT, _INSTRUCTION]
    if memory_block_text.strip():
        parts.append(f"【相关记忆】\n{memory_block_text.strip()}")
    return "\n\n".join(parts)


def compose_human(case: HumanenessCase) -> str:
    lines: list[str] = []
    if case.history:
        for turn in case.history:
            who = "用户" if turn.role == "user" else AGENT_NAME
            lines.append(f"{who}：{turn.text}")
    lines.append(f"用户：{case.current_user}")
    lines.append(f"{AGENT_NAME}：")
    return "\n".join(lines)
