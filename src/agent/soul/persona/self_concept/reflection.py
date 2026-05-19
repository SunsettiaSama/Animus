from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config.soul.config import SoulConfig
from agent.soul.handlers.tao.types import TaoRunRequest, TaoRunResult
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.status.emotional import EmotionalAnchor

from .concept import SelfConcept

_REFLECTION_SYSTEM = """\
你是 Agent 的自我叙事层，正在进行日终自我反省。

要求：
- 以第一人称回顾今天的主观体验，可调用 soul_persona / soul_memory_search / soul_life_chronicle / soul_life_hot 查阅材料
- 反思未付诸行动的念头、犹豫与自我质疑
- 完成推理后，在最终 Finish 回答中输出且仅输出如下 JSON（不要 markdown 代码块）：
{"thought_records": ["..."], "reflective_note": "100字以内自由自省，无则空字符串"}"""

_OUTPUT_SCHEMA = """{
  "thought_records": ["今天浮现但未付诸行动的念头"],
  "reflective_note": "一段自由自省（100字以内，无则空字符串）"
}"""


@dataclass
class SelfReflectionResult:
    thought_records: list[str] = field(default_factory=list)
    reflective_note: str = ""

    def is_empty(self) -> bool:
        return not self.thought_records and not self.reflective_note.strip()

    def render_for_evolver(self) -> str:
        parts: list[str] = []
        if self.thought_records:
            parts.append(
                "【日终反省 · 未付诸行动的念头】\n"
                + "\n".join(f"- {t}" for t in self.thought_records)
            )
        if self.reflective_note.strip():
            parts.append(f"【日终反省 · 自由自省】\n{self.reflective_note.strip()}")
        return "\n\n".join(parts)


class TaoReflectionSession:
    """构造发往 Base Tao 的日终反省请求。"""

    @classmethod
    def build_request(
        cls,
        profile: PersonaProfile,
        concept: SelfConcept,
        today_dialogue: str,
        today_scheduler_tasks: str,
        recent_anchors: list[EmotionalAnchor] | None = None,
        profile_name: str | None = None,
    ) -> TaoRunRequest:
        tao_profile = profile_name or SoulConfig.default().tao_reflection_profile_name
        anchor_section = ""
        if recent_anchors:
            lines = [
                f"- [{a.ts[:10]}] {a.event} → {a.felt}"
                for a in recent_anchors[-8:]
            ]
            anchor_section = "\n\n【近期情绪锚点】\n" + "\n".join(lines)

        instruction = (
            f"【基本性格】\n{profile.render()}\n\n"
            f"【当前自我叙事】\n{concept.narrative or '（暂无）'}\n\n"
            f"【今日对话摘要】\n{today_dialogue or '（今天暂无对话）'}\n\n"
            f"【今日完成任务】\n{today_scheduler_tasks or '（今天暂无任务）'}"
            f"{anchor_section}\n\n"
            "请结合工具与上述材料完成日终自我反省。"
            f"最终回答必须是 JSON：\n{_OUTPUT_SCHEMA}"
        )
        return TaoRunRequest(
            instruction=instruction,
            profile_name=tao_profile,
            system_note=_REFLECTION_SYSTEM,
        )


class ReflectionDecomposer:
    """从 Base Tao 完整推理链拆解出 self_concept 可用的反省材料。"""

    @classmethod
    def decompose(cls, tao_result: TaoRunResult) -> SelfReflectionResult:
        parsed = cls._parse_json_payload(tao_result.answer)
        if parsed is not None:
            return parsed

        trace_thoughts = [
            s.thought.strip()
            for s in tao_result.steps
            if s.thought.strip()
        ]
        note = tao_result.answer.strip()
        if not note and trace_thoughts:
            note = trace_thoughts[-1][:200]
        return SelfReflectionResult(
            thought_records=trace_thoughts[-5:],
            reflective_note=note[:200],
        )

    @classmethod
    def _parse_json_payload(cls, raw: str) -> SelfReflectionResult | None:
        text = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return None
        d = json.loads(m2.group(0))
        return SelfReflectionResult(
            thought_records=[t for t in d.get("thought_records", []) if t],
            reflective_note=str(d.get("reflective_note", "")).strip(),
        )
