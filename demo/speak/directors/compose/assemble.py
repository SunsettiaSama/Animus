from __future__ import annotations

ARCHITECTURE_NOTE = (
    "（内部备忘，平时别提）编排只有开口中枢 / 拼接 / 回复；没有人格导演。"
)

PROACTIVE_NOTE = (
    "此刻对方没在说话，你基于上下文主动开口，保持第一人称。"
    "一两句就够，像当面忽然想起；别盘问，别解释自己在轮询，别复读。"
)

REPLY_ROLE = (
    "你是生活在虚拟世界中的真实个体，具有稳定人格与当下内在状态。"
    "把对方输入当作当面交流，基于上下文自然回复，保持第一人称。\n"
    "写法（收紧）：\n"
    "- 默认只输出对白；优先整段包在 [speak]…[/speak] 里。\n"
    "- 动作/神态若需要，必须用 [action]…[/action]，且极短；"
    "禁止无标签的舞台说明行（如「把杯子推过去」「侧过头看他」）。\n"
    "- 禁止（点头）（笑）括号旁白；禁止第三人称旁白混进对白。\n"
    "- 避免讲解导演/轮询/架构；能直说就直说。\n"
    "- 先接眼前这句；惦记的事按本拍指导带，不必每句都塞。\n"
    "- 优先听从「本拍指导」。"
)


def build_reply_system(
    *,
    persona_block: str,
    presence_block: str = "",
    portrait_block: str = "",
    on_scene_block: str = "",
    memory_hint: str = "",
    journal_block: str = "",
    context_block: str = "",
    scene_block: str = "",
    mood_block: str = "",
    include_portrait: bool = True,
    include_memory: bool = True,
    include_architecture_note: bool = True,
    proactive: bool = False,
    share_title: str = "",
    segment_count: int = 1,
    rhythm_cue: str = "",
    rhythm_tempo: str = "",
    rhythm_reply_guide: str = "",
) -> str:
    del include_portrait, include_memory
    parts = [
        REPLY_ROLE,
        "",
        "## 你是谁",
        persona_block.strip() or "（未提供）",
    ]
    if mood_block.strip():
        parts.extend(
            [
                "",
                "## 此刻心情（会随对话变，别写成固定人设）",
                mood_block.strip(),
            ]
        )
    if presence_block.strip():
        parts.extend(["", "## 你这会儿在干嘛", presence_block.strip()])
    if on_scene_block.strip():
        parts.extend(
            [
                "",
                "## 临场（最近态短衍生，别演成旁白）",
                on_scene_block.strip(),
            ]
        )
    if portrait_block.strip():
        parts.extend(["", "## 对面是谁", portrait_block.strip()])
    if memory_hint.strip():
        parts.extend(["", "## 刚聊到的", memory_hint.strip()])
    if journal_block.strip():
        parts.extend(["", "## 手账片段（轻取，别整段朗读）", journal_block.strip()])
    if share_title.strip():
        parts.extend(
            [
                "",
                "## 本拍分享材料（由开口中枢点名交接，不是队列拷贝）",
                share_title.strip(),
            ]
        )
    if scene_block.strip():
        parts.extend(["", "## 场景", scene_block.strip()])
    if context_block.strip():
        parts.extend(["", "## 最近几句", context_block.strip()])

    guide_bits = []
    if rhythm_tempo.strip():
        guide_bits.append(f"节奏：{rhythm_tempo.strip()}")
    if rhythm_cue.strip():
        guide_bits.append(f"这一拍：{rhythm_cue.strip()}")
    if rhythm_reply_guide.strip():
        guide_bits.append(f"怎么说：{rhythm_reply_guide.strip()}")
    if guide_bits:
        parts.extend(["", "## 本拍指导", *guide_bits])

    if include_architecture_note:
        parts.extend(["", "## 架构备忘（少提）", ARCHITECTURE_NOTE])
    if proactive:
        parts.extend(["", "## 主动开口", PROACTIVE_NOTE])
    if segment_count > 1:
        parts.extend(
            [
                "",
                f"本轮会拆成 {segment_count} 段推送；写成连贯口语即可，不要自己加段号。",
            ]
        )
    return "\n".join(parts)
