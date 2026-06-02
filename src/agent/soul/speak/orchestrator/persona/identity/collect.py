from __future__ import annotations

from agent.soul.persona.distill.schema import PersonaDistillPack

from ..limits import STABLE_HARD_MAX_CHARS, clamp_identity_text


def collect_stable_portrait(
    *,
    persona_snap: dict,
    max_chars: int = STABLE_HARD_MAX_CHARS,
) -> str:
    """从 persona_distill.general 读取稳定人格（profile+self_concept 已蒸馏合并）。"""
    distill = persona_snap.get("persona_distill")
    if distill is None:
        raise RuntimeError(
            "persona_distill missing: 请先 build 画像并确保蒸馏完成（portrait_revision 对齐）"
        )
    if isinstance(distill, PersonaDistillPack):
        pack = distill
    elif isinstance(distill, dict):
        pack = PersonaDistillPack.from_dict(distill)
    else:
        raise RuntimeError("persona_distill missing: 无效的 persona_distill 类型")

    portrait = pack.slice("general")
    if not portrait:
        raise RuntimeError(
            "persona_distill.general missing: 请先完成 general 切片蒸馏"
        )
    return clamp_identity_text(portrait, hard_max=max_chars)
