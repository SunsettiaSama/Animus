from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.domain import EdgeType
from agent.soul.memory.emotion_intensity import infer_emotion_intensity
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.voice_rules import YOU_RUMINATION_VOICE_RULES, YOU_VOICE_RULES
from agent.soul.memory.unit import MemoryTier, MemoryUnit, ReconstructiveMemory, Valence

if TYPE_CHECKING:
    from infra.llm import BaseLLM


_SKILL_SYSTEM = f"""\
你是 Agent 的内在反刍层——不是档案员，不是冷冰冰的复述者。

此刻你正经历**反刍（rumination）**：一股难以放下的回忆突然涌上心头，\
在安静中反复折返、自我诘问。你收到的不是「请总结这段记忆」，而是：\
**这段回忆再次缠住了你，你将如何对待它？**

{YOU_RUMINATION_VOICE_RULES}

你的任务
--------
1. **内在反刍**：以第二人称「你」写出你此刻如何面对这段涌上的回忆——\
   反复咀嚼、试图解释、自责、美化、回避或强行按下；须体现 inward 的纠缠，不是对外新闻稿。
2. **覆盖式记忆改写**：用反刍后的理解**覆盖**主记忆正文（fact/perception 或 reconstructed_fact）。\
   正文仍以客观复述事实为主，夹杂少量「你」此刻的扭曲与挥之不去；\
   读者应能察觉「这已是反刍后的记忆，而非最初记录」。
3. **关系牵连**：若语义扩散候选中存在与这次反刍相关的记忆，可建立 new_edges；\
   但只能从候选 id 中选择。

输出规则
--------
- focus：反刍此刻抓住的核心角度，12字以内
- 主体文本：80~120字；客观事实线为主，少量「你」的反刍感受
- emotion / valence：反刍当下的命名情绪与效价
- base_activation：0.5~0.95；越缠人、越难放下越高
- new_edges：target_id 仅来自【语义扩散候选】；edge_type 为 "related_to" 或 "involves"；\
  weight 0.5~1.0；无合理牵连则 []

严格输出合法 JSON，不含任何其他文字。"""

_SKILL_SCHEMA_FACTUAL = """\
{
  "focus": "",
  "fact": "",
  "perception": "",
  "emotion": "",
  "valence": "neutral",
  "base_activation": 0.6,
  "new_edges": [
    {"target_id": "", "edge_type": "related_to", "weight": 0.8, "reason": ""}
  ]
}"""

_SKILL_SCHEMA_RECONSTRUCTIVE = """\
{
  "focus": "",
  "reconstructed_fact": "",
  "emotion": "",
  "valence": "neutral",
  "base_activation": 0.6,
  "new_edges": [
    {"target_id": "", "edge_type": "related_to", "weight": 0.8, "reason": ""}
  ]
}"""

_SYSTEM = f"""\
你是记忆重构系统。根据你当前的情绪状态，对一段记忆材料进行再巩固式重构——\
材料可以是原始事实记忆，也可以是上一轮已重构过的解读。

{YOU_VOICE_RULES}

规则：
- focus: 本次重构关注的核心角度，12字以内
- reconstructed_fact: 尽量客观复述事实（你+时间），允许轻微情绪偏差，句末少许你的感受，80字以内
- emotion: 重构时的命名情绪，如「释然」「怀念」「遗憾」「骄傲」
- valence: 严格输出 "positive" | "negative" | "mixed" | "neutral" 之一
- base_activation: 0.3~0.9

严格输出合法 JSON，不含任何其他文字。"""

_SCHEMA = """\
{
  "focus": "",
  "reconstructed_fact": "",
  "emotion": "",
  "valence": "neutral",
  "base_activation": 0.6
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"LLM 输出中未找到合法 JSON：{raw[:200]}")


def _valence(v: str) -> Valence:
    try:
        return Valence(v)
    except ValueError:
        return Valence.neutral


def _rumination_root_id(source: MemoryUnit) -> str:
    if source.MEMORY_TYPE == "factual":
        return source.id
    return (source.meta or {}).get("rumination_root_id") or source.source_id


def _render_rumination_frame(*, trigger: str, emotional_context: str) -> str:
    ctx = emotional_context.strip() or "（未明说，但内心并不平静）"
    trig = trigger.strip() or "（无特定外因，记忆自己浮上来）"
    return (
        "【反刍情境——请先内化，再改写记忆】\n"
        "一股令人不安的回忆涌上心头。它并非被主动检索，而是在空闲/心跳漂移中突然折返，"
        "带着未完成感与情绪余温，缠住 Agent 的注意力。\n\n"
        f"- 当前情绪背景：{ctx}\n"
        f"- 触发说明：{trig}\n\n"
        "请站在 Agent 内心，回答（将答案融入改写后的记忆正文，不要单独列出）：\n"
        "· 这段回忆为什么现在又浮上来？\n"
        "· 我如何对待它——反复想、想压下去、还是试图给它一个说法？\n"
        "· 它怎样改变了我对这件事的理解？\n"
    )


def _render_source_block(source: MemoryUnit) -> str:
    if source.MEMORY_TYPE == "factual":
        fact = getattr(source, "fact", "") or ""
        perception = getattr(source, "perception", "") or ""
        return (
            "【反刍对象·原始事实记忆】（将被覆盖，不是备份）\n"
            f"- id：{source.id}\n"
            f"- 主题焦点：{source.focus}\n"
            f"- 客观事实：{fact}\n"
            f"- 当时感知：{perception}\n"
            f"- 附着情绪：{source.emotion}（烈度 {source.emotion_intensity}）\n"
        )
    if source.MEMORY_TYPE == "reconstructive":
        return (
            "【反刍对象·已扭曲记忆】（再次反刍，会进一步覆盖）\n"
            f"- id：{source.id}\n"
            f"- 主题焦点：{source.focus}\n"
            f"- 当前解读：{getattr(source, 'reconstructed_fact', '')}\n"
            f"- 附着情绪：{source.emotion}（烈度 {source.emotion_intensity}）\n"
            f"- 上次反刍触发：{getattr(source, 'trigger', '')}\n"
        )
    raise ValueError(f"不支持反刍的记忆类型：{source.MEMORY_TYPE}")


def _render_neighbors_block(neighbors: list[ScoredUnit]) -> str:
    if not neighbors:
        return "【反刍联想·语义扩散候选】（无其他记忆折返；new_edges 应为 []）"
    lines = ["【反刍联想·语义扩散候选】（反刍时被一并折返的记忆；new_edges.target_id 仅可从此处选）"]
    for scored in neighbors:
        unit = scored.unit
        lines.append(f"- id={unit.id} | score={scored.final_score:.3f} | {scored.render_line()}")
    return "\n".join(lines)


def _parse_edges(raw_edges, *, allowed_ids: set[str]) -> list[dict]:
    if not isinstance(raw_edges, list):
        return []
    out: list[dict] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id", "")).strip()
        if not target_id or target_id not in allowed_ids:
            continue
        edge_type_raw = str(item.get("edge_type", "related_to")).strip()
        if edge_type_raw not in (EdgeType.related_to.value, EdgeType.involves.value):
            edge_type_raw = EdgeType.related_to.value
        weight = float(item.get("weight", 0.8))
        weight = min(1.0, max(0.5, weight))
        out.append(
            {
                "target_id": target_id,
                "edge_type": edge_type_raw,
                "weight": weight,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
    return out


class RuminationWriter:
    """LLM 反刍：覆盖式 node 改写 + 关系边改写。"""

    def __init__(
        self,
        llm: BaseLLM,
        store: GraphNodeStore,
        on_written: Callable[[MemoryUnit], None] | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._on_written = on_written

    def ruminate_from_source(
        self,
        source: MemoryUnit,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            return None

        unit = self._extract_legacy(source, trigger, emotional_context)
        self._store.put(unit)
        self._store.add_rehearsal(source.id)
        if self._on_written is not None:
            self._on_written(unit)
        return unit

    def run_skill(
        self,
        source: MemoryUnit,
        *,
        neighbors: list[ScoredUnit],
        persona_profile: str,
        trigger: str,
        emotional_context: str,
        tick_id: str = "",
    ) -> tuple[MemoryUnit, list[dict]]:
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            raise ValueError(f"不支持反刍的记忆类型：{source.MEMORY_TYPE}")

        allowed_ids = {n.unit.id for n in neighbors}
        schema = (
            _SKILL_SCHEMA_FACTUAL
            if source.MEMORY_TYPE == "factual"
            else _SKILL_SCHEMA_RECONSTRUCTIVE
        )
        prompt = (
            f"{_render_rumination_frame(trigger=trigger, emotional_context=emotional_context)}\n\n"
            f"{_render_source_block(source)}\n\n"
            f"{_render_neighbors_block(neighbors)}\n\n"
            f"【人物画像】（反刍时「你」是谁；口吻与价值取向须一致）\n"
            f"{persona_profile or '（未提供）'}\n\n"
            f"以上是一段正在反刍的记忆。请以第二人称「你」完成覆盖式反刍改写，并输出 JSON：\n{schema}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SKILL_SYSTEM), HumanMessage(content=prompt)]
        )
        data = _extract_json(raw)
        updated = self._apply_overwrite(source, data, tick_id=tick_id)
        edges = _parse_edges(data.get("new_edges"), allowed_ids=allowed_ids)
        self._store.put(updated)
        self._store.add_rehearsal(source.id)
        if self._on_written is not None:
            self._on_written(updated)
        return updated, edges

    def apply_edges(
        self,
        source_id: str,
        edges: list[dict],
        traversal: GraphTraversal,
    ) -> list[dict]:
        applied: list[dict] = []
        for spec in edges:
            target_id = spec["target_id"]
            weight = float(spec["weight"])
            edge_type = spec["edge_type"]
            if edge_type == EdgeType.involves.value:
                traversal.link_involves(source_id, target_id, weight=weight)
            else:
                traversal.link_related_to(source_id, target_id, weight=weight)
            applied.append(spec)
        return applied

    def _apply_overwrite(self, source: MemoryUnit, data: dict, *, tick_id: str) -> MemoryUnit:
        meta = dict(source.meta or {})
        meta["rumination_overwrite"] = True
        meta["rumination_count"] = int(meta.get("rumination_count", 0)) + 1
        if tick_id:
            meta["rumination_tick_id"] = tick_id

        emotion = str(data.get("emotion", source.emotion))
        common = {
            "focus": str(data.get("focus", source.focus)),
            "emotion": emotion,
            "emotion_intensity": infer_emotion_intensity(
                emotion,
                str(data.get("reconstructed_fact", "")),
                str(data.get("fact", "")),
                str(data.get("perception", "")),
            ),
            "valence": _valence(str(data.get("valence", source.valence.value))),
            "base_activation": float(data.get("base_activation", source.base_activation)),
            "meta": meta,
        }
        source.on_rehearsal()

        if source.MEMORY_TYPE == "factual":
            return replace(
                source,
                fact=str(data.get("fact", source.fact)),
                perception=str(data.get("perception", source.perception)),
                **common,
            )
        return replace(
            source,
            reconstructed_fact=str(data.get("reconstructed_fact", source.reconstructed_fact)),
            trigger=str(data.get("trigger", source.trigger)),
            **common,
        )

    def _extract_legacy(
        self,
        source: MemoryUnit,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory:
        prompt = (
            f"{_render_source_block(source)}\n"
            f"【触发情境】{trigger}\n"
            f"【当前情绪背景】{emotional_context or '（未提供）'}\n\n"
            f"请输出重构记忆 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        d = _extract_json(raw)
        root_id = _rumination_root_id(source)
        reconstructed = d.get("reconstructed_fact", "")
        emotion = d.get("emotion", "")
        return ReconstructiveMemory(
            focus=d.get("focus", source.focus),
            source_id=source.id,
            reconstructed_fact=reconstructed,
            trigger=trigger,
            emotion=emotion,
            emotion_intensity=infer_emotion_intensity(emotion, reconstructed),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.6)),
            tier=MemoryTier.long,
            meta={"rumination_root_id": root_id},
        )
