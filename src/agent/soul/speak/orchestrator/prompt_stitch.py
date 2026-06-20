from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bundle import SpeakPromptBundle

def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(section for section in sections if section.strip())


def _orchestrator_dynamic_body(bundle: SpeakPromptBundle) -> str:
    """orchestrator 动态块：persona / 对话者 / 场景 / 引导，以自然段软衔接。"""
    parts: list[str] = []

    for block in bundle.persona.render_blocks():
        text = block.strip()
        if text:
            parts.append(text)

    interactor = bundle.persona.render_interactor_block().strip()
    if interactor:
        parts.append(interactor)

    for block in bundle.scene.render_blocks():
        text = block.strip()
        if text:
            parts.append(text)

    for block in bundle.guidance.render_orchestrator_blocks():
        text = block.strip()
        if text:
            parts.append(text)

    if not parts:
        return ""
    return "\n\n".join(parts)


def assemble_turn_system(bundle: SpeakPromptBundle) -> str:
    """主接口 system：规则 → 编排动态 → 上下文蒸馏 → 工作记忆 → 输出格式（均为软边界叙述）。"""
    sections: list[str] = []

    role = bundle.system.role.strip()
    if role:
        sections.append(role)

    orchestrator_body = _orchestrator_dynamic_body(bundle)
    if orchestrator_body:
        sections.append(orchestrator_body)

    distill = bundle.guidance.context_distill.strip()
    if distill:
        sections.append(distill)

    working_memory = bundle.guidance.working_memory.strip()
    if working_memory:
        sections.append(working_memory)

    output_format = bundle.system.output_format.strip()
    if output_format:
        sections.append(output_format)

    return _join_sections(sections)
