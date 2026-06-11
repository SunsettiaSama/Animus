from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.speak.orchestrator import SpeakPromptBundle, SpeakTurnMode
    from agent.soul.speak.session.manage.coordinator import SessionSocialManager
    from agent.soul.speak.session.manage.types import (
        EnterGreetingTurnSpec,
        InitiativeHint,
        SilenceBreakTurnSpec,
    )

INITIATIVE_PROMPT = (
    "你不必只做被动应答。除回答用户外，若还适合做一句极短的承接、反问或轻量延展，"
    "可在 think 里先判断「本轮是否要主动多开口一句」。"
    "用户刚抛出明确新话题时优先简明应答；若仅应答即可则 speak 保持简短并以 finish 结束；"
    "若适合轻量主动可在 speak 末尾加一句自然追问；若确有分享冲动且待分享队列非空可用 share。"
    "勿每轮都主动，克制比话多更重要。"
)


def render_enter_greeting_block(spec: EnterGreetingTurnSpec) -> str:
    angle = spec.angle.strip()
    angle_clause = f"话头可参考：{angle.rstrip('。')}。" if angle else ""
    lines = [
        f"用户进入对话窗口已约 {int(spec.elapsed_sec)} 秒，尚未发言。",
        "你可在 think 里揣摩是否适合用一句极短、自然的话头先开口；"
        "若无合适开口则 finish 且不写 speak。",
    ]
    if angle_clause:
        lines.append(angle_clause)
    if spec.dialogue_compressed.strip():
        lines.append(
            "近期对话脉络：" + spec.dialogue_compressed.strip().rstrip("。") + "。"
        )
    return " ".join(lines)


def render_silence_break_block(spec: SilenceBreakTurnSpec) -> str:
    angle = spec.angle.strip()
    angle_clause = f"揣摩方向可参考：{angle.rstrip('。')}。" if angle else ""
    lines = [
        f"用户在你上一句之后已静默约 {int(spec.elapsed_sec)} 秒，尚未发来新消息。",
        "你可在 think 里揣摩对方是否在忙、在思考或话未说完，"
        "再决定是否用一句极短的承接或轻问打破沉默；若无合适开口则 finish 且不写 speak。",
    ]
    if angle_clause:
        lines.append(angle_clause)
    if spec.dialogue_compressed.strip():
        lines.append(
            "近期对话脉络：" + spec.dialogue_compressed.strip().rstrip("。") + "。"
        )
    return " ".join(lines)


def resolve_enter_greeting_user_text(spec: EnterGreetingTurnSpec) -> str:
    return f"（系统：用户进入会话已约 {int(spec.elapsed_sec)} 秒，尚未发言。）"


def resolve_silence_break_user_text(spec: SilenceBreakTurnSpec) -> str:
    return f"（系统：用户已静默约 {int(spec.elapsed_sec)} 秒，无新消息。）"


def resolve_social_user_text(bundle: SpeakPromptBundle, fallback: str) -> str:
    meta = bundle.meta
    for key in ("silence_break_user", "enter_greeting_user"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    user = str(bundle.user_text or "").strip()
    if user:
        return user
    return fallback.strip()


def apply_session_social_guidance(
    bundle: SpeakPromptBundle,
    *,
    enter_greeting: EnterGreetingTurnSpec | None = None,
    silence_break: SilenceBreakTurnSpec | None = None,
    initiative: InitiativeHint | None = None,
) -> None:
    if enter_greeting is not None:
        bundle.guidance.social_blocks.append(render_enter_greeting_block(enter_greeting))
        bundle.notes.append(
            f"enter_greeting: armed elapsed={int(enter_greeting.elapsed_sec)}s"
        )
        bundle.meta["enter_greeting"] = True
        bundle.meta["enter_greeting_user"] = resolve_enter_greeting_user_text(enter_greeting)
        return

    if silence_break is not None:
        bundle.guidance.social_blocks.append(render_silence_break_block(silence_break))
        bundle.notes.append(
            f"silence_break: armed elapsed={int(silence_break.elapsed_sec)}s"
        )
        bundle.meta["silence_break"] = True
        bundle.meta["silence_break_user"] = resolve_silence_break_user_text(silence_break)
        return

    if initiative is not None:
        bundle.guidance.social_blocks.append(initiative.text)
        bundle.notes.append(initiative.note)


def apply_session_social(
    bundle: SpeakPromptBundle,
    social: SessionSocialManager,
    *,
    session_id: str,
    turn_index: int,
    user_text: str,
    mode: SpeakTurnMode = "inbound",
    social_include: bool = True,
    social_armed: str | None = None,
) -> None:
    if not social_include:
        return

    if social_armed == "enter_greeting":
        armed_greeting = social.enter_greeting.pop_armed_turn(session_id)
        if armed_greeting is not None:
            apply_session_social_guidance(bundle, enter_greeting=armed_greeting)
        return

    if social_armed == "silence_break":
        armed = social.silence.pop_armed_turn(session_id)
        if armed is not None:
            apply_session_social_guidance(bundle, silence_break=armed)
        return

    if social_armed == "initiative":
        hint = social.evaluate_initiative(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            mode=mode,
        )
        if hint is not None:
            apply_session_social_guidance(bundle, initiative=hint)
        return

    armed_greeting = social.enter_greeting.pop_armed_turn(session_id)
    if armed_greeting is not None:
        apply_session_social_guidance(bundle, enter_greeting=armed_greeting)
        return

    armed = social.silence.pop_armed_turn(session_id)
    if armed is not None:
        apply_session_social_guidance(bundle, silence_break=armed)
        return

    hint = social.evaluate_initiative(
        session_id,
        turn_index=turn_index,
        user_text=user_text,
        mode=mode,
    )
    if hint is not None:
        apply_session_social_guidance(bundle, initiative=hint)
