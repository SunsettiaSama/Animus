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
        presence = snap.get("presence") or {}
        affect = snap.get("presence_affect") or presence.get("affect") or {}
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
        if presence:
            from agent.soul.presence.state import PresenceState

            rendered = PresenceState.from_dict(presence).render()
            if rendered:
                parts += ["", "【当下状态】", rendered]
        else:
            affect_line = (affect.get("narrative") or affect.get("texture") or "").strip()
            if affect_line:
                parts += ["", "【当下情感】", affect_line]
        kws = snap.get("attention_keywords") or []
        if kws:
            parts += ["", "【检索偏置关键词】", ", ".join(kws[:12])]
        return "\n".join(parts)
