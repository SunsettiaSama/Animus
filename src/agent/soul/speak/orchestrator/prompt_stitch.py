from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bundle import SpeakPromptBundle

_LEGACY_SECTION_MARKERS = (
    "【系统提示",
    "【编排态",
    "【角色画像",
    "【对话者画像",
    "【场景叙事",
    "【对话引导 ·",
    "【当前对话 ·",
    "【当前会话 ·",
    "【输出格式 ·",
)


def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(section for section in sections if section.strip())


def _strip_legacy_section_wrapper(text: str) -> str:
    """去掉旧版硬边界帧头（兼容缓存/测试夹具）。"""
    normalized = text.strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    if lines and any(lines[0].startswith(marker) for marker in _LEGACY_SECTION_MARKERS):
        body: list[str] = []
        skip_preamble = True
        for line in lines[1:]:
            if skip_preamble and (
                not line.strip()
                or line.startswith("以下为")
                or line.startswith("以下由")
                or line.startswith("以下规定")
                or line.startswith("以下为你")
                or line.startswith("请将其作为")
                or line.startswith("用于锚定")
                or line.startswith("用于把握")
                or line.startswith("回复时须")
                or line.startswith("可内化")
            ):
                continue
            skip_preamble = False
            body.append(line)
        return "\n".join(body).strip()
    return normalized


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
    if not distill and bundle.persona.dialogue_compressed.strip():
        distill = bundle.persona.dialogue_compressed.strip()
    if distill:
        sections.append(_strip_legacy_section_wrapper(distill))

    working_memory = bundle.guidance.working_memory.strip()
    if working_memory:
        sections.append(_strip_legacy_section_wrapper(working_memory))

    output_format = bundle.system.output_format.strip()
    if output_format:
        sections.append(output_format)

    return _join_sections(sections)
