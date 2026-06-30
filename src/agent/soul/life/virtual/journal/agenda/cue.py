from __future__ import annotations

from .item import LandmarkAgenda


def build_landmark_agenda_public_cue(agenda: LandmarkAgenda) -> str:
    parts = [
        "【触发来源】journal_landmark_agenda",
        f"【landmark_agenda_id】{agenda.id}",
        f"【目标日期】{agenda.target_date}",
        f"【公开议程标题】{agenda.title.strip()}",
        f"【公开议程摘要】{agenda.summary.strip()}",
        f"【完整议程上下文】{agenda.full_context.strip()}",
    ]
    if agenda.scene_hint.strip():
        parts.append(f"【预期场景锚点】{agenda.scene_hint.strip()}")
    if agenda.scene_id.strip():
        parts.append(f"【绑定 scene_id】{agenda.scene_id.strip()}")
    if agenda.scene_name.strip():
        parts.append(f"【绑定 scene_name】{agenda.scene_name.strip()}")
    if agenda.scene_cards:
        parts.append("【绑定 scene cards】")
        for card in agenda.scene_cards:
            affordances = "、".join(card.affordances) if card.affordances else "（无）"
            conditions = "、".join(card.conditions) if card.conditions else "（无）"
            parts.append(
                f"- {card.title}：{card.description.strip()}；"
                f"可互动：{affordances}；使用条件：{conditions}"
            )
    if agenda.steps:
        parts.append("【计划步骤】")
        parts.extend(f"- {step.strip()}" for step in agenda.steps if step.strip())
    if agenda.success_criteria:
        parts.append("【完成标准】")
        parts.extend(f"- {item.strip()}" for item in agenda.success_criteria if item.strip())
    if agenda.constraints:
        parts.append("【边界约束】")
        parts.extend(f"- {item.strip()}" for item in agenda.constraints if item.strip())
    parts.append(
        "【主持规则】以上议程为 Soul 与 storyview 共享的公开未来行动声明；"
        "你只能据此主持问题和选项，不得替 Soul 决定最终行动或动机，"
        "不得引入议程未声明的新线索、角色、物件或悬疑支线；"
        "不得离开绑定 scene，不得引入 scene cards 未覆盖的新地点或物件。"
    )
    return "\n".join(parts)
