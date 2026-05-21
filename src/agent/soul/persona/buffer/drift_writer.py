from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import BeliefStrength, SelfConcept, SelfConceptDelta

from .clustering import DriftClusterConfig, DriftUnitCluster


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    m2 = re.search(r"\{[\s\S]*\}", text)
    if not m2:
        raise ValueError(f"DriftWriter: LLM 输出中未找到合法 JSON：{raw[:300]}")
    return json.loads(m2.group(0))


_CLUSTER_SYSTEM = """\
你是 Agent 的自我叙事层，正在对一组相关记忆做簇内蒸馏。
只输出 JSON，不要 markdown 代码块。"""

_CLUSTER_SCHEMA = """{
  "theme": "簇主题（简短）",
  "insight": "第一人称，2-4句，描述这组记忆对我意味着什么",
  "adds": [{"content": "我...", "strength": "emerging"}],
  "upgrades": [{"match": "信念关键词", "to": "established"}],
  "removes": ["待弱化的信念关键词"]
}"""

_MERGE_SYSTEM = """\
你是 Agent 的自我叙事层，正在把两个局部自我洞察合并为一段更上层的叙事片段。
只输出 JSON，不要 markdown 代码块。"""

_MERGE_SCHEMA = """{
  "insight": "合并后的第一人称叙事片段（3-6句）",
  "adds": [],
  "upgrades": [],
  "removes": []
}"""

_REVISE_SYSTEM = """\
你是 Agent 的自我叙事修订层。给定当前自我画像、蒸馏草稿与信念候选，
产出相对当前 self_concept 的最小变更（无变化则对应字段留空）。
只输出 JSON，不要 markdown 代码块。"""

_REVISE_SCHEMA = """{
  "narrative": "修订后的自我叙事摘要（100-280字；若草稿不足以改变则空字符串）",
  "adds": [{"content": "我...", "strength": "emerging"}],
  "upgrades": [{"match": "信念关键词", "to": "established"}],
  "removes": ["待弱化或移除的信念关键词"]
}"""


@dataclass
class ClusterDraft:
    theme: str
    insight: str = ""
    adds: list[dict] = field(default_factory=list)
    upgrades: list[dict] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.insight.strip()
            and not self.adds
            and not self.upgrades
            and not self.removes
        )


@dataclass
class MonthDraft:
    month: str
    insight: str = ""
    cluster_drafts: list[ClusterDraft] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.insight.strip() and all(d.is_empty() for d in self.cluster_drafts)


class DriftDistillWriter:
    """漂移写入 skill：簇内蒸馏 → 向上合并 → 对照画像修订。"""

    def __init__(self, llm: BaseLLM, *, cfg: DriftClusterConfig | None = None) -> None:
        self._llm = llm
        self._cfg = cfg or DriftClusterConfig()

    def distill_cluster(
        self,
        cluster: DriftUnitCluster,
        profile: PersonaProfile,
        concept: SelfConcept,
    ) -> ClusterDraft:
        lines = cluster.lines(
            max_lines=self._cfg.max_lines_per_cluster,
            max_content=self._cfg.line_max_chars,
        )
        evidence = "\n".join(f"- {line}" for line in lines) or "（本簇暂无可读记忆行）"
        related_beliefs = self._related_beliefs(concept, cluster.theme)
        belief_text = "\n".join(f"- {b}" for b in related_beliefs) or "（无直接相关信念）"
        prompt = (
            f"【基本性格摘要】\n{self._profile_hint(profile)}\n\n"
            f"【当前自我叙事】\n{concept.narrative or '（暂无）'}\n\n"
            f"【相关信念】\n{belief_text}\n\n"
            f"【本簇主题】{cluster.theme}\n"
            f"【簇内记忆】\n{evidence}\n\n"
            f"请完成簇内蒸馏，输出 JSON：\n{_CLUSTER_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_CLUSTER_SYSTEM), HumanMessage(content=prompt)]
        )
        data = _extract_json(raw)
        return ClusterDraft(
            theme=str(data.get("theme", cluster.theme)).strip() or cluster.theme,
            insight=str(data.get("insight", "")).strip(),
            adds=list(data.get("adds") or []),
            upgrades=list(data.get("upgrades") or []),
            removes=[str(x) for x in data.get("removes") or [] if str(x).strip()],
        )

    def reduce_drafts(self, drafts: list[ClusterDraft], *, month: str) -> MonthDraft:
        if not drafts:
            return MonthDraft(month=month)
        if len(drafts) == 1:
            d = drafts[0]
            return MonthDraft(month=month, insight=d.insight, cluster_drafts=list(drafts))

        layer = list(drafts)
        while len(layer) > 1:
            next_layer: list[ClusterDraft] = []
            i = 0
            while i < len(layer):
                left = layer[i]
                if i + 1 >= len(layer):
                    next_layer.append(left)
                    break
                right = layer[i + 1]
                merged = self._merge_pair(left, right, month=month)
                next_layer.append(merged)
                i += 2
            layer = next_layer

        root = layer[0]
        return MonthDraft(month=month, insight=root.insight, cluster_drafts=list(drafts))

    def revise_against_portrait(
        self,
        profile: PersonaProfile,
        concept: SelfConcept,
        month_draft: MonthDraft,
    ) -> SelfConceptDelta:
        if month_draft.is_empty():
            return SelfConceptDelta()

        belief_candidates = self._aggregate_belief_ops(month_draft.cluster_drafts)
        adds_text = json.dumps(belief_candidates["adds"], ensure_ascii=False)
        upg_text = json.dumps(belief_candidates["upgrades"], ensure_ascii=False)
        rm_text = json.dumps(belief_candidates["removes"], ensure_ascii=False)
        prompt = (
            f"【基本性格】\n{profile.render()}\n\n"
            f"【当前自我叙事】\n{concept.narrative or '（暂无）'}\n\n"
            f"【当前信念】\n{self._beliefs_block(concept)}\n\n"
            f"【本月蒸馏草稿】（{month_draft.month}）\n{month_draft.insight}\n\n"
            f"【簇级信念候选】\n"
            f"adds: {adds_text}\n"
            f"upgrades: {upg_text}\n"
            f"removes: {rm_text}\n\n"
            f"请对照前后画像产出最小修订，输出 JSON：\n{_REVISE_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_REVISE_SYSTEM), HumanMessage(content=prompt)]
        )
        data = _extract_json(raw)
        return SelfConceptDelta(
            narrative=str(data.get("narrative", "")).strip(),
            upgrades=list(data.get("upgrades") or []),
            adds=list(data.get("adds") or []),
            removes=[str(x) for x in data.get("removes") or [] if str(x).strip()],
        )

    def _merge_pair(self, left: ClusterDraft, right: ClusterDraft, *, month: str) -> ClusterDraft:
        prompt = (
            f"【月份】{month}\n\n"
            f"【片段 A：{left.theme}】\n{left.insight or '（空）'}\n\n"
            f"【片段 B：{right.theme}】\n{right.insight or '（空）'}\n\n"
            f"请合并为更上层的自我叙事片段，输出 JSON：\n{_MERGE_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_MERGE_SYSTEM), HumanMessage(content=prompt)]
        )
        data = _extract_json(raw)
        theme = f"{left.theme} / {right.theme}"
        return ClusterDraft(
            theme=theme,
            insight=str(data.get("insight", "")).strip(),
            adds=list(data.get("adds") or []),
            upgrades=list(data.get("upgrades") or []),
            removes=[str(x) for x in data.get("removes") or [] if str(x).strip()],
        )

    @staticmethod
    def _profile_hint(profile: PersonaProfile) -> str:
        traits = "、".join(profile.core_traits[:4]) if profile.core_traits else ""
        head = profile.name or "Agent"
        if traits:
            return f"{head}：{traits}"
        return head

    @staticmethod
    def _related_beliefs(concept: SelfConcept, theme: str) -> list[str]:
        theme_lower = theme.strip().lower()
        if not theme_lower:
            return [b.content for b in concept.top_beliefs(k=3)]
        matched = [b.content for b in concept.beliefs if theme_lower in b.content.lower()]
        if matched:
            return matched[:4]
        return [b.content for b in concept.top_beliefs(k=2, min_strength=BeliefStrength.established)]

    @staticmethod
    def _beliefs_block(concept: SelfConcept) -> str:
        lines = [f"- [{b.strength.value}] {b.content}" for b in concept.beliefs[:12]]
        return "\n".join(lines) if lines else "（暂无信念）"

    @staticmethod
    def _aggregate_belief_ops(drafts: list[ClusterDraft]) -> dict[str, list]:
        adds: list[dict] = []
        upgrades: list[dict] = []
        removes: list[str] = []
        seen_add: set[str] = set()
        seen_upg: set[str] = set()
        seen_rm: set[str] = set()
        for draft in drafts:
            for item in draft.adds:
                content = str(item.get("content", "")).strip()
                if content and content not in seen_add:
                    seen_add.add(content)
                    adds.append(item)
            for item in draft.upgrades:
                key = str(item.get("match", "")).strip()
                if key and key not in seen_upg:
                    seen_upg.add(key)
                    upgrades.append(item)
            for kw in draft.removes:
                text = str(kw).strip()
                if text and text not in seen_rm:
                    seen_rm.add(text)
                    removes.append(text)
        return {"adds": adds, "upgrades": upgrades, "removes": removes}
