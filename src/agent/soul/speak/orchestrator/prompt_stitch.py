from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bundle import SpeakPromptBundle

_FRAME_SYSTEM_ROLE = (
    "【系统提示 · 规则参考】\n"
    "以下为系统级提示，定义你在此会话中的基本处境；"
    "请将其作为重要的规则参考，而非剧情正文。"
)

_FRAME_ORCHESTRATOR = (
    "【编排态 · 本轮动态】\n"
    "以下由 orchestrator 汇总的 persona / 场景 / 引导等复杂动态块；"
    "用于锚定你是谁、当下场景与接话倾向；可内化，勿逐条汇报或当作台词。"
)

_FRAME_CONTEXT_DISTILL = (
    "【当前对话 · 上下文蒸馏】\n"
    "以下为当前会话内已完成的对话压缩摘要；"
    "把握已谈过的脉络，勿与下方工作记忆原文混淆。"
)

_FRAME_WORKING_MEMORY = (
    "【当前会话 · 工作记忆】\n"
    "以下为最近几轮与用户的对白原文（尚未纳入蒸馏）；"
    "用于接续当下话题，随后将进入本轮用户输入。"
)

_FRAME_PERSONA = (
    "【角色画像 · 扮演锚定】\n"
    "以下为你的角色画像与当下状态，供你锚定「你是谁、此刻怎样」。"
    "回复时须以此为准，避免 OOC（不得偏离稳定人格与给定状态）；"
    "勿把下列内容当作可直接念出的台词。"
)

_FRAME_INTERACTOR = (
    "【对话者画像 · 对方是谁】\n"
    "以下为你此刻交谈对象的画像，用于把握对方是谁、与你关系如何；"
    "可内化，勿逐句复述或当作对白模板。"
)

_FRAME_SCENE = (
    "【场景叙事 · 世界锚点】\n"
    "以下为当前场景与世界侧客观描述，帮助你把握环境与氛围；"
    "可内化，勿逐句复述或剧透式堆砌。"
)

_FRAME_GUIDANCE = (
    "【对话引导 · 本轮倾向】\n"
    "以下为对话组织与社交倾向参考，"
    "用于把握如何接话、是否接续话题；不是要你逐条汇报。"
)

_FRAME_OUTPUT = (
    "【输出格式 · 硬性约束】\n"
    "以下规定标签结构与结束态；生成回复时必须遵守。"
)


def _wrap_section(frame: str, body: str) -> str:
    text = body.strip()
    if not text:
        return ""
    return f"{frame.strip()}\n\n{text}"


def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(section for section in sections if section.strip())


def _orchestrator_dynamic_body(bundle: SpeakPromptBundle) -> str:
    """orchestrator 复杂动态块：persona + 对话者 + 场景 + 引导（不含蒸馏/工作记忆）。"""
    parts: list[str] = []

    persona_parts = bundle.persona.render_blocks()
    if persona_parts:
        body = "\n\n".join(part for part in persona_parts if part.strip())
        wrapped = _wrap_section(_FRAME_PERSONA, body)
        if wrapped:
            parts.append(wrapped)

    interactor = bundle.persona.render_interactor_block()
    if interactor:
        wrapped = _wrap_section(_FRAME_INTERACTOR, interactor)
        if wrapped:
            parts.append(wrapped)

    scene_parts = bundle.scene.render_blocks()
    if scene_parts:
        body = "\n\n".join(part for part in scene_parts if part.strip())
        wrapped = _wrap_section(_FRAME_SCENE, body)
        if wrapped:
            parts.append(wrapped)

    guidance_parts = bundle.guidance.render_orchestrator_blocks()
    if guidance_parts:
        body = "\n\n".join(part for part in guidance_parts if part.strip())
        wrapped = _wrap_section(_FRAME_GUIDANCE, body)
        if wrapped:
            parts.append(wrapped)

    if not parts:
        return ""
    return "\n\n".join(parts)


def assemble_turn_system(bundle: SpeakPromptBundle) -> str:
    """主接口 system 顺序：规则 → 编排动态 → 上下文蒸馏 → 工作记忆 → 输出格式。"""
    sections: list[str] = []

    role = bundle.system.role.strip()
    if role:
        sections.append(_wrap_section(_FRAME_SYSTEM_ROLE, role))

    orchestrator_body = _orchestrator_dynamic_body(bundle)
    if orchestrator_body:
        sections.append(_wrap_section(_FRAME_ORCHESTRATOR, orchestrator_body))

    distill = bundle.guidance.context_distill.strip()
    if not distill and bundle.persona.dialogue_compressed.strip():
        distill = bundle.persona.dialogue_compressed.strip()
    if distill:
        if distill.startswith("【当前对话"):
            sections.append(distill)
        else:
            sections.append(_wrap_section(_FRAME_CONTEXT_DISTILL, distill))

    working_memory = bundle.guidance.working_memory.strip()
    if working_memory:
        if working_memory.startswith("【当前会话"):
            sections.append(working_memory)
        else:
            sections.append(_wrap_section(_FRAME_WORKING_MEMORY, working_memory))

    output_format = bundle.system.output_format.strip()
    if output_format:
        sections.append(_wrap_section(_FRAME_OUTPUT, output_format))

    return _join_sections(sections)
