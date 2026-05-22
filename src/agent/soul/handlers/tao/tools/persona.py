from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from agent.react.action.base import BaseAction


class SoulPersonaArgs(BaseModel):
    pass


class SoulPersonaAction(BaseAction):
    """经 Soul 接口读取 profile、self_concept 与 Presence.affect。"""

    name: str = "soul_persona"
    description: str = (
        "读取 Agent 当前人格：静态 profile、自我叙事 self_concept、"
        "当下态附属情绪状态 presence_affect。无参数。"
    )
    args_model: ClassVar[type[BaseModel]] = SoulPersonaArgs

    soul: Any = None

    def execute(self, **kwargs) -> str:
        if self.soul is None:
            return "Soul Persona 服务未就绪。"
        snap = self.soul.query_persona()
        profile = snap.get("profile") or {}
        concept = snap.get("self_concept") or {}
        affect = snap.get("presence_affect") or {}
        parts = [
            "【静态画像】",
            f"名称：{profile.get('name', '')}",
            f"背景：{profile.get('background', '')}",
            f"特质：{', '.join(profile.get('traits') or profile.get('core_traits') or [])}",
            f"价值观：{', '.join(profile.get('values') or [])}",
            f"风格：{profile.get('style', '')}",
        ]
        narrative = (concept.get("narrative") or "").strip()
        if narrative:
            parts += ["", "【自我叙事】", narrative]
        beliefs = concept.get("beliefs") or []
        if beliefs:
            parts.append("")
            parts.append("【信念】")
            for b in beliefs[:6]:
                parts.append(f"- [{b.get('strength', '')}] {b.get('content', '')}")
        texture = (affect.get("texture") or "").strip()
        if texture:
            parts += ["", "【驱动情绪质感】", texture]
        anchors = affect.get("anchors") or []
        if anchors:
            parts.append("")
            parts.append("【近期情绪锚点】")
            for a in anchors[-5:]:
                parts.append(
                    f"- [{str(a.get('ts', ''))[:10]}] {a.get('event', '')} → {a.get('felt', '')}"
                )
        kws = snap.get("attention_keywords") or []
        if kws:
            parts += ["", "【检索偏置关键词】", ", ".join(kws[:12])]
        return "\n".join(parts)
