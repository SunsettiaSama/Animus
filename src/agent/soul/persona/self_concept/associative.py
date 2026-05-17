from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.profile.profile import PersonaProfile
from .concept import BeliefStrength, SelfConcept, SelfConceptDelta

_SYSTEM = """\
你是一个AI助手的联想反思系统。给定几条随机浮现的记忆，判断它们之间是否存在跨时间的共同模式，\
并从中提炼新的自我认识。

这不是对近期事件的总结，而是"走神式"的联想——就像人在发呆时忽然意识到"我好像总是在 X 情境下 Y"。

规则：
- 只有当这些记忆之间有真正有意义的共同模式时，才输出信念种子
- 若找不到有意义的连接，pattern 和 seeds 均输出空
- seeds 最多 1~2 条，必须是第一人称陈述，描述跨记忆的行为/情绪倾向
- 所有种子的 strength 固定为 "emerging"——它只是一个待验证的候选，不是已确立的事实
- 不更新叙事，不升级已有信念，不删除任何信念
- 严格输出合法 JSON，不含任何其他文字"""

_SCHEMA = """\
{
  "pattern": "（描述跨记忆的共同模式，若无则为空字符串）",
  "seeds": [
    {"content": "我在...情境下往往..."}
  ]
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    return {}


def _render_memory(unit) -> str:
    """将单条浮现记忆渲染为可读文本（兼容 ScoredUnit 和 MemoryUnit）。"""
    u = getattr(unit, "unit", unit)
    parts = [f"[{u.MEMORY_TYPE}] 主题：{u.focus}"]
    for attr in ("fact", "reconstructed_fact", "narrative"):
        val = getattr(u, attr, "")
        if val:
            parts.append(f"内容：{val[:120]}")
            break
    if u.emotion:
        parts.append(f"情绪：{u.emotion}（烈度 {u.emotion_intensity:.1f}）")
    return "  ".join(parts)


class AssociativeEvolver:
    """联想启发式演进器——从 wander() 浮现的记忆中发现跨时间模式。

    定位
    ----
    - 独立于时间轴演进（daily review），由 wander tick（30分钟）触发
    - 只产出 emerging 信念种子，不更新叙事，不升级/删除已有信念
    - 与时间轴演进形成互补：联想路径播种，时间轴路径验证并升级

    心理学依据
    ----------
    默认模式网络（DMN）在"走神"状态下整合跨时间的自传性记忆，
    形成无意识的模式识别，是创造力和自我认识的重要来源。
    """

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def evolve(
        self,
        wandered: list,
        concept: SelfConcept,
        profile: PersonaProfile,
    ) -> SelfConceptDelta:
        """从浮现的记忆中联想提炼 emerging 信念候选。

        参数
        ----
        wandered
            wander() 返回的 ScoredUnit 列表（通常 2~3 条）
        concept
            当前 SelfConcept（用于去重检查，避免重复播种）
        profile
            稳定基础画像（提供人格背景参考）

        返回
        ----
        SelfConceptDelta，只含 adds（emerging），其余字段为空。
        若无有意义的模式，返回空 delta。
        """
        if not wandered:
            return SelfConceptDelta()

        memories_text = "\n".join(
            f"{i + 1}. {_render_memory(m)}" for i, m in enumerate(wandered)
        )
        existing_beliefs = "\n".join(
            f"- [{b.strength.value}] {b.content}" for b in concept.beliefs
        ) or "（暂无）"

        prompt = (
            f"【基础画像】\n{profile.render()}\n\n"
            f"【刚才随机浮现的记忆（共 {len(wandered)} 条，来自不同时间）】\n"
            f"{memories_text}\n\n"
            f"【当前已有信念（仅供去重参考）】\n{existing_beliefs}\n\n"
            f"这些记忆有什么跨时间的共同模式吗？输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw)

    def _parse(self, raw: str) -> SelfConceptDelta:
        d = _extract_json(raw)
        seeds = d.get("seeds", [])
        adds = [
            {"content": s.get("content", "").strip(), "strength": "emerging"}
            for s in seeds
            if s.get("content", "").strip()
        ]
        return SelfConceptDelta(adds=adds)
