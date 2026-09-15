"""AB 管线到轨迹评委的适配：ABRecord → 拟人管线的 DialogueRecord 形状。"""
from __future__ import annotations

from evals.memory_humaneness.dialogue.simulator import DialogueRecord, DialogueTurn


def dialogue_record_from_ab(scenario, record) -> DialogueRecord:
    """把 ABRecord 转成 ExpertDialogueJudge 需要的 DialogueRecord。

    记忆行不可得（AB 不走检索基座），评委的 memory_naturalness 维度
    在 AB 语境下读作"边缘念头呈现的自然度"，与检索质量无关——与
    软约束实验的问题定义一致。
    """
    return DialogueRecord(
        scenario_id=record.scenario_id,
        theme=f"{scenario.theme}（AB-{record.arm}）",
        base=record.arm,
        turns=[DialogueTurn(index=t.index, user=t.user, agent=t.agent,
                            memory_lines=[])
               for t in record.turns],
        elapsed_sec=record.elapsed_sec,
        error=record.error,
    )
