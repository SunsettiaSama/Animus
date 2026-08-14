from __future__ import annotations

from agent.soul.persona.distill.schema import PersonaDistillPack

from ..limits import STABLE_HARD_MAX_CHARS, clamp_identity_text

DIRECTOR_PORTRAIT_MAX_CHARS = 180


def _load_distill_pack(persona_snap: dict) -> PersonaDistillPack:
    distill = persona_snap.get("persona_distill")
    if distill is None:
        raise RuntimeError(
            "persona_distill missing: 请先 build 画像并确保蒸馏完成（portrait_revision 对齐）"
        )
    if isinstance(distill, PersonaDistillPack):
        return distill
    if isinstance(distill, dict):
        return PersonaDistillPack.from_dict(distill)
    raise RuntimeError("persona_distill missing: 无效的 persona_distill 类型")


def collect_stable_portrait(
    *,
    persona_snap: dict,
    max_chars: int = STABLE_HARD_MAX_CHARS,
) -> str:
    """从 persona_distill.general 读取稳定人格（profile+self_concept 已蒸馏合并）。"""
    pack = _load_distill_pack(persona_snap)
    portrait = pack.slice("general")
    if not portrait:
        raise RuntimeError(
            "persona_distill.general missing: 请先完成 general 切片蒸馏"
        )
    return clamp_identity_text(portrait, hard_max=max_chars)


def collect_director_portrait(
    *,
    persona_snap: dict,
    max_chars: int = DIRECTOR_PORTRAIT_MAX_CHARS,
) -> str:
    """导演侧精简画像：优先 director 切片，缺省回落 reasoning → general。"""
    pack = _load_distill_pack(persona_snap)
    portrait = (
        pack.director_text()
        or pack.slice("reasoning")
        or pack.slice("general")
    )
    if not portrait:
        raise RuntimeError(
            "persona_distill.director missing: 请先完成 director 切片蒸馏（或至少 general）"
        )
    return clamp_identity_text(portrait, hard_max=max_chars)
