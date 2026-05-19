from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.memory.unit import ReconstructiveMemory
from agent.soul.persona.status.emotional import EmotionalAnchor
from agent.soul.persona.profile.profile import PersonaProfile
from .concept import BeliefStrength, SelfConcept, SelfConceptDelta
from .reflection import SelfReflectionResult

# ── Step 1：叙事更新 ──────────────────────────────────────────────────────────

_NARRATIVE_SYSTEM = """\
你是一个AI助手的自传叙事系统。根据近期的情绪事件，判断是否需要更新其自我叙事摘要。

叙事摘要是第一人称的，描述"我是谁、我的经历如何塑造了现在的我"，100-200字。

规则：
- 只在近期事件具有阶段性意义时才更新叙事，否则输出空字符串
- 如果更新，要自然地融入新体验，而不是简单地列举事件
- 保持连贯性：新叙事应延续旧叙事的基调，而非推翻它
- 严格输出纯文本（新叙事内容）或空字符串，不加任何格式标记"""

# ── Step 2：信念提取 ──────────────────────────────────────────────────────────

_BELIEF_SYSTEM = """\
你是一个AI助手的自我信念提取系统。对比旧信念列表和新叙事，判断信念是否需要调整。

信念强度分三级：
- emerging    刚出现，基于 1~2 次经验
- established 多次验证，相对稳定
- core        深度认同，形成人格底色

规则：
- match 字段用几个关键词定位已有信念（无需完整复制内容）
- 升级是单步的：emerging→established 或 established→core，不能跨级
- 新增信念必须在新叙事中有明确依据，strength 一律从 emerging 开始
- 移除仅用于信念明确被新叙事所否定的情况
- 优先考虑"不变化"，大多数情况下输出空列表
- 严格输出合法 JSON，不含任何其他文字"""

_BELIEF_SCHEMA = """\
{
  "upgrades": [
    {"match": "几个定位关键词", "to": "established"}
  ],
  "adds": [
    {"content": "我在...方面...", "strength": "emerging"}
  ],
  "removes": ["定位关键词"]
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    return {}


class SelfConceptEvolver:
    """两步 LLM 演化器：叙事优先，信念从叙事派生。

    Step 1  narrative_update()
        LLM 读取近期情绪锚点 → 判断是否更新叙事（自由文本）
        LLM 最擅长做这件事：语义理解 + 文本生成

    Step 2  belief_delta()
        LLM 对比旧信念列表与新叙事 → 输出结构化 delta
        关键词匹配而非 ID 匹配，避免 UUID 幻觉

    不持有状态，不决定何时调用，由 Heartbeat 日终自我反省触发。
    """

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def evolve(
        self,
        concept: SelfConcept,
        built_profile: PersonaProfile,
        recent_anchors: list[EmotionalAnchor],
        recent_ruminations: list[ReconstructiveMemory] | None = None,
        daily_reflection: SelfReflectionResult | None = None,
    ) -> SelfConceptDelta:
        """主入口：两步调用，返回 SelfConceptDelta。

        参数
        ----
        recent_ruminations
            反刍（RuminationWriter）产出的 ReconstructiveMemory 列表（可选）。
            反刍是经过 LLM 二次反思的高质量材料，在叙事更新时优先于原始锚点。
            由 PersonaManager.evolve_self_concept() 从 LTM 查询后传入。
        """
        # Step 1：叙事更新（核心，可能为空）
        new_narrative = self._narrative_update(
            current_narrative=concept.narrative,
            profile=built_profile,
            anchors=recent_anchors,
            ruminations=recent_ruminations or [],
            daily_reflection=daily_reflection,
        )

        # Step 2：信念提取——仅在叙事真正更新时才运行
        # 叙事未变 → 信念无新依据，跳过可避免无效 LLM 调用和对稳定信念的随机扰动
        if new_narrative and concept.narrative != new_narrative:
            belief_delta = self._belief_delta(
                current_beliefs=concept.beliefs,
                narrative=new_narrative,
            )
        else:
            belief_delta = SelfConceptDelta()

        return SelfConceptDelta(
            narrative=new_narrative,
            upgrades=belief_delta.upgrades,
            adds=belief_delta.adds,
            removes=belief_delta.removes,
        )

    # ── Step 1 ────────────────────────────────────────────────────────────────

    def _narrative_update(
        self,
        current_narrative: str,
        profile: PersonaProfile,
        anchors: list[EmotionalAnchor],
        ruminations: list[ReconstructiveMemory],
        daily_reflection: SelfReflectionResult | None = None,
    ) -> str:
        """让 LLM 判断是否需要更新叙事，返回新叙事文本或空字符串。

        优先级：日终反省 > 反刍记忆 > 原始情绪锚点。
        三者都为空时跳过，不调用 LLM。
        """
        if not anchors and not ruminations and (
            daily_reflection is None or daily_reflection.is_empty()
        ):
            return ""

        reflection_section = ""
        if daily_reflection is not None and not daily_reflection.is_empty():
            reflection_section = (
                f"\n\n{daily_reflection.render_for_evolver()}"
            )

        rumination_section = ""
        if ruminations:
            lines = [
                f"- {r.focus}：{r.reconstructed_fact[:80]}"
                for r in ruminations[-5:]
            ]
            rumination_section = (
                f"\n\n【近期反刍记忆（经过反思，优先参考）（共 {len(ruminations)} 条）】\n"
                + "\n".join(lines)
            )

        anchor_section = ""
        if anchors:
            anchor_section = (
                f"\n\n【近期原始情绪事件（共 {len(anchors)} 条）】\n"
                + self._render_anchors(anchors)
            )

        prompt = (
            f"【基础画像】\n{profile.render()}\n\n"
            f"【当前叙事摘要】\n{current_narrative or '（暂无）'}"
            f"{reflection_section}"
            f"{rumination_section}"
            f"{anchor_section}\n\n"
            "如果以上材料（尤其是日终反省与反刍记忆）具有阶段性意义，请更新叙事摘要（100-200字）；"
            "否则只输出空字符串。"
        )
        result = self._llm.generate_messages(
            [SystemMessage(content=_NARRATIVE_SYSTEM), HumanMessage(content=prompt)]
        ).strip()

        # 空字符串、"无"、引号包裹的空字符串等均视为无更新
        if not result or result in ('""', "''", "无", "（无）", "null"):
            return ""
        return result

    # ── Step 2 ────────────────────────────────────────────────────────────────

    def _belief_delta(
        self,
        current_beliefs: list,
        narrative: str,
    ) -> SelfConceptDelta:
        """让 LLM 对比旧信念与新叙事，输出结构化 delta。"""
        beliefs_text = self._render_beliefs(current_beliefs)
        prompt = (
            f"【当前叙事摘要】\n{narrative}\n\n"
            f"【当前信念列表】\n{beliefs_text or '（暂无信念）'}\n\n"
            f"请判断信念是否需要调整，输出 JSON：\n{_BELIEF_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_BELIEF_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse_belief_delta(raw)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_anchors(self, anchors: list[EmotionalAnchor]) -> str:
        lines = []
        for a in anchors[-10:]:
            lines.append(f"- [{a.ts[:10]}] {a.event} → {a.felt}")
        return "\n".join(lines)

    def _render_beliefs(self, beliefs: list) -> str:
        if not beliefs:
            return ""
        lines = []
        for b in beliefs:
            strength = b.strength.value if hasattr(b.strength, "value") else str(b.strength)
            lines.append(f"- [{strength}] {b.content}")
        return "\n".join(lines)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_belief_delta(self, raw: str) -> SelfConceptDelta:
        d = _extract_json(raw)
        return SelfConceptDelta(
            upgrades=d.get("upgrades", []),
            adds=d.get("adds", []),
            removes=d.get("removes", []),
        )
