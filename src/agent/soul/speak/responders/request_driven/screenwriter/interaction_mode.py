from __future__ import annotations

from typing import Literal

# 交互通道备注：当前对方↔世界主要靠文字发言 / 静默可观测。
# 编剧按 mode 写场记：有说法才引用对方内容；静默时尽量写场面与角色侧。
InteractionMode = Literal["user_utterance", "user_silent", "no_utterance"]

_MODE_LABEL = {
    "user_utterance": "user_utterance｜对方有可引用说法",
    "user_silent": "user_silent｜对方静默（有沉默日志）",
    "no_utterance": "no_utterance｜对方尚未开口",
}

_MODE_POLICY = {
    "user_utterance": (
        "处理：尽可能围绕对方已说出的内容写可观察过程；"
        "对方未说出口的意图/情绪尽量留给后文自然浮现。"
    ),
    "user_silent": (
        "处理：尽可能写场面、光线、物件、角色手上的空档；"
        "对方外在动作（触碰、抬眼、去拿某物等）尽量先不写；"
        "side.user_activity 用静默占位即可。"
    ),
    "no_utterance": (
        "处理：对方尚未开口时，尽可能写场景与角色侧可见事实；"
        "side.user_activity 保持中性在场。"
    ),
}


def resolve_interaction_mode(
    user_text: str,
    *,
    silence_log_ready: bool = False,
) -> InteractionMode:
    text = str(user_text or "").strip()
    if not text:
        return "user_silent" if silence_log_ready else "no_utterance"
    lowered = text.lower()
    if lowered == "silence" or text.startswith("（系统：") or "无输入" in text:
        return "user_silent" if silence_log_ready else "no_utterance"
    if "用户进入会话" in text:
        return "no_utterance"
    return "user_utterance"


def interaction_mode_label(mode: InteractionMode) -> str:
    return _MODE_LABEL[mode]


def interaction_mode_policy(mode: InteractionMode) -> str:
    return _MODE_POLICY[mode]


def interaction_annotation_block(mode: InteractionMode) -> str:
    return (
        f"[交互通道]\n"
        f"mode={interaction_mode_label(mode)}\n"
        f"{interaction_mode_policy(mode)}\n"
        "说明：当前对方↔世界主要靠文字发言/静默可观测；"
        "触碰、注视、位移等通道若材料里没有，尽量先不写。"
    )


def silence_user_activity_placeholder() -> str:
    return "在场，未观察到外在动作"


def no_utterance_user_activity_placeholder() -> str:
    return "在场，尚未开口"
