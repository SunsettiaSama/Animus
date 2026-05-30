from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.graph.networks.experience_block import ExperienceBlock, read_experience_block
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.types import ExperienceKind

from infra.llm import BaseLLM

_ROUTE_SYSTEM = """\
你是记忆路由系统。根据 Life 体验单元原文，判断应写入哪类长期记忆图：

- event：客观发生的事件、场景、事实片段（与「某次发生了什么」相关）
- social：与特定交互者相关的主观关系、印象、称呼、特质、互动感受

只输出 JSON，不要解释。"""

_ROUTE_SCHEMA = """\
{
  "network": "event|social",
  "reason": "一句话路由理由"
}"""


@dataclass(frozen=True)
class RouteDecision:
    network: ExperienceKind
    reason: str


@dataclass(frozen=True)
class ExperienceIngestResult:
    network: ExperienceKind
    reason: str
    nodes: list[BaseNode]


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"记忆路由未返回 JSON：{raw[:200]}")
    return json.loads(m.group())


def parse_experience_network(raw: str) -> ExperienceKind:
    text = raw.strip().lower()
    if text in ("social", "anchor"):
        return ExperienceKind.anchor
    return ExperienceKind.event


def route_experience_block(
    llm: BaseLLM,
    block: ExperienceBlock,
) -> tuple[ExperienceBlock, str]:
    decision = _llm_route_block(llm, block)
    return replace(block, kind=decision.network), decision.reason


def _llm_route_block(llm: BaseLLM, block: ExperienceBlock) -> RouteDecision:
    prompt = (
        f"体验 id：{block.experience_id}\n"
        f"交互者 id：{block.interactor_id}\n"
        f"来源：{block.source}\n"
        f"体验原文：\n{block.raw_text}\n"
        f"情绪线索：{block.emotion_label or '（未标注）'} "
        f"显著性={block.salience:.2f}\n\n"
        f"输出 schema：\n{_ROUTE_SCHEMA}"
    )
    raw = llm.generate_messages(
        [SystemMessage(content=_ROUTE_SYSTEM), HumanMessage(content=prompt)]
    )
    data = _extract_json(raw)
    network = parse_experience_network(str(data.get("network", "event")))
    reason = str(data.get("reason", "")).strip()
    return RouteDecision(network=network, reason=reason)


class ExperienceGraphIngest:
    """ExperienceUnit → 记忆图节点（可选 LLM 路由 event / social）。"""

    def __init__(
        self,
        event: EventMemoryNetwork,
        social: SocialMemoryNetwork,
        llm: BaseLLM | None = None,
    ) -> None:
        self._event = event
        self._social = social
        self._llm = llm

    def route_block(self, block: ExperienceBlock) -> tuple[ExperienceBlock, str]:
        if self._llm is None:
            raise RuntimeError("route_block 需要 LLM")
        return route_experience_block(self._llm, block)

    def create_nodes(
        self,
        unit: ExperienceUnit,
        *,
        agent_persona_narrative: str = "",
        route: bool | None = None,
    ) -> ExperienceIngestResult:
        block = read_experience_block(unit)
        persona = agent_persona_narrative.strip()
        use_route = route if route is not None else self._llm is not None

        if use_route:
            if self._llm is None:
                raise RuntimeError("create_nodes(route=True) 需要 LLM")
            routed_block, reason = route_experience_block(self._llm, block)
        else:
            routed_block = block
            reason = ""

        if routed_block.kind == ExperienceKind.anchor:
            written = self._social.ingest_anchor_experience(
                unit,
                block=routed_block,
                agent_persona_narrative=persona,
            )
        else:
            node = self._event.ingest_event_experience(
                unit,
                block=routed_block,
                agent_persona_narrative=persona,
            )
            written = [node]

        network = routed_block.kind
        return ExperienceIngestResult(
            network=network,
            reason=reason,
            nodes=list(written),
        )
