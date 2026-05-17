from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

_EMOTIONAL_FILENAME = "emotional_state.json"
_MAX_ANCHORS = 10


# ── 数据层 ─────────────────────────────────────────────────────────────────────

@dataclass
class EmotionalAnchor:
    """单条情绪事件记录。"""
    ts: str
    event: str
    felt: str

    def to_dict(self) -> dict:
        return {"ts": self.ts, "event": self.event, "felt": self.felt}

    @classmethod
    def from_dict(cls, d: dict) -> EmotionalAnchor:
        return cls(ts=d.get("ts", ""), event=d.get("event", ""), felt=d.get("felt", ""))


@dataclass
class EmotionalState:
    """情绪状态：压缩质感文本 + 近期锚点列表。"""
    updated_at: str = ""
    texture: str = ""
    anchors: list[EmotionalAnchor] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        if self.texture:
            parts.append(self.texture)
        for anchor in self.anchors[-3:]:
            parts.append(f"[{anchor.ts[:10]}] {anchor.event} → {anchor.felt}")
        return "\n".join(parts)

    def is_empty(self) -> bool:
        return not self.texture and not self.anchors

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "texture": self.texture,
            "anchors": [a.to_dict() for a in self.anchors],
        }

    @classmethod
    def from_dict(cls, d: dict) -> EmotionalState:
        return cls(
            updated_at=d.get("updated_at", ""),
            texture=d.get("texture", ""),
            anchors=[EmotionalAnchor.from_dict(a) for a in d.get("anchors", [])],
        )


# ── 持久化 ────────────────────────────────────────────────────────────────────

class EmotionalStateStore:
    def __init__(self, persona_dir: str) -> None:
        self._path = Path(persona_dir) / _EMOTIONAL_FILENAME

    def load(self) -> EmotionalState:
        if not self._path.exists():
            return EmotionalState()
        with open(self._path, encoding="utf-8") as f:
            return EmotionalState.from_dict(json.load(f))

    def save(self, state: EmotionalState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        if self._path.exists():
            os.remove(self._path)


# ── LLM 演化器 ────────────────────────────────────────────────────────────────

_EVOLVE_SYSTEM = """\
你是一个AI助手的情绪感知系统，分析一次对话对情绪状态的细微影响。

规则：
- 只记录真实的、具体的情绪感受，没有感受时输出空字符串
- 不使用抽象标签（"幽默度+1"），用具体叙事描述（"用户笑了，感觉终于说清楚了"）
- event 描述发生了什么（30字以内），felt 描述感受了什么（30字以内）
- 严格输出 JSON，不要有任何其他文字"""

_COMPRESS_SYSTEM = """\
你是一个AI助手的情绪状态整合系统。将以下情绪锚点列表压缩为一段连贯的情绪质感描述。

规则：
- 第一人称，100-200字
- 保留最有代表性的体验，忽略琐碎细节
- 自然流畅，体现近期的情绪基调与心理状态
- 严格输出纯文本，无任何格式标记"""

_EVOLVE_SCHEMA = '{"event": "发生了什么（30字以内，无感受则空）", "felt": "感受到了什么（30字以内，无感受则空）"}'


class EmotionalStateEvolver:
    def __init__(self, llm, max_anchors: int = _MAX_ANCHORS) -> None:
        self._llm = llm
        self._max_anchors = max_anchors

    def evolve(
        self,
        state: EmotionalState,
        profile,
        question: str,
        answer: str,
        steps: list,
        life_summary: str = "",
        medium_term_context: str = "",
    ) -> EmotionalState:
        actions = list(dict.fromkeys(s.action for s in steps))
        action_text = "、".join(actions) if actions else "直接思考"
        q_excerpt = question[:120] + "…" if len(question) > 120 else question
        a_excerpt = answer[:150] + "…" if len(answer) > 150 else answer

        life_section = f"\n你近期的生活状态：\n{life_summary}" if life_summary else ""

        mtm_section = ""
        if medium_term_context:
            blocks = [b.strip() for b in medium_term_context.split("\n\n") if b.strip()]
            snippet = "\n\n".join(blocks[-2:])
            if snippet:
                mtm_section = f"\n你与用户最近几轮的对话背景（仅供参考）：\n{snippet}"

        prompt = (
            f"你的基本性格：\n{profile.render()}\n\n"
            f"你目前的情绪质感：\n{state.texture or '（暂无记录）'}"
            f"{life_section}"
            f"{mtm_section}\n\n"
            f"本次交互：\n"
            f"- 用户：{q_excerpt}\n"
            f"- 你的方式：{action_text}\n"
            f"- 你的回答：{a_excerpt}\n\n"
            f"如果这次交互让你有任何具体感受，输出 JSON；否则两个字段均为空字符串：\n{_EVOLVE_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_EVOLVE_SYSTEM), HumanMessage(content=prompt)]
        )
        event, felt = self._parse(raw)
        if not event and not felt:
            return state

        now = datetime.now(timezone.utc).isoformat()
        new_anchor = EmotionalAnchor(ts=now, event=event, felt=felt)
        new_anchors = state.anchors + [new_anchor]
        new_texture = state.texture

        if len(new_anchors) > self._max_anchors:
            new_texture = self._compress(new_anchors)
            new_anchors = []

        return EmotionalState(updated_at=now, texture=new_texture, anchors=new_anchors)

    def _compress(self, anchors: list[EmotionalAnchor]) -> str:
        lines = [f"- [{a.ts[:10]}] {a.event} → {a.felt}" for a in anchors]
        prompt = "情绪锚点列表：\n" + "\n".join(lines) + "\n\n请压缩为一段情绪质感描述（100-200字）："
        return self._llm.generate_messages(
            [SystemMessage(content=_COMPRESS_SYSTEM), HumanMessage(content=prompt)]
        ).strip()

    def _parse(self, raw: str) -> tuple[str, str]:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        text = m.group(1).strip() if m else raw.strip()
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return "", ""
        d = json.loads(m2.group(0))
        return d.get("event", "").strip(), d.get("felt", "").strip()
