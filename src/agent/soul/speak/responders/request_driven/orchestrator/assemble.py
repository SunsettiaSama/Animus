from __future__ import annotations

from typing import TYPE_CHECKING

from .blocks.guidance.session_bridge import (
    render_interrupt_system_block,
    resolve_social_user_text,
)

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.stream import SpeakAgentOutput
    from agent.soul.speak.session.queue.types import InterruptContext

    from .bundle import SpeakPromptBundle

APPEND_CONTINUE_INSTRUCTION = (
    "请继续完成本轮尚未说完的内容；输出仍需包含 [think]…[/think] 与 "
    "[state]finish[/state]（或 [state]append[/state]）。"
)

# 角色路径只续写可见台词，不注入 compose 状态或旧交付动作。
APPEND_CONTINUE_CHARACTER = (
    "请继续完成本轮尚未说完的内容；仅输出一个完整的 <speak>简短台词</speak>。"
)


def build_turn_system(
    bundle: SpeakPromptBundle,
    *,
    interrupt_context: InterruptContext | None = None,
    round_idx: int = 0,
    partial_output: str = "",
    parsed: SpeakAgentOutput | None = None,
    for_character: bool = False,
) -> str:
    if for_character:
        from .prompt_stitch import assemble_character_system

        system = assemble_character_system(bundle)
    else:
        system = bundle.build_system()
    if interrupt_context is not None:
        system = f"{system}\n\n{render_interrupt_system_block(interrupt_context)}"
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        continue_hint = (
            APPEND_CONTINUE_CHARACTER if for_character else APPEND_CONTINUE_INSTRUCTION
        )
        system = f"{system}\n\n{continue_hint}"
        if partial_output.strip():
            from agent.soul.speak.responders.request_driven.protocol.scrub import (
                scrub_compose_markup,
            )

            fragment = (
                scrub_compose_markup(partial_output)
                if for_character
                else partial_output.strip()
            )
            if fragment:
                system = (
                    f"{system}\n\n已输出片段如下，请接着说完、不要重复：\n{fragment}"
                )
    brew_hint = bundle.meta.get("recent_brew_lines")
    if isinstance(brew_hint, str) and brew_hint.strip():
        hint = brew_hint.strip()
        if for_character:
            from agent.soul.speak.responders.request_driven.protocol.scrub import (
                scrub_compose_markup,
            )

            hint = scrub_compose_markup(hint)
        if hint:
            system = f"{system}\n\n请勿重复以下内容：{hint}"
    return system


def resolve_llm_user_text(
    bundle: SpeakPromptBundle,
    user_text: str,
    *,
    round_idx: int = 0,
    parsed: SpeakAgentOutput | None = None,
) -> str:
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        return "请接着说完，不要重复已输出内容。"
    return resolve_social_user_text(bundle, user_text)
