from __future__ import annotations

from .schema import PersonaDistillPack

_DIALOGUE_MAX_CHARS = 240


def _trunc(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _normalize_dialogue_body(body: str) -> str:
    """旧版带【对话人格】+ 字段行时，Speak 仍只注入正文；新版为纯自述段落。"""
    lines = body.splitlines()
    if lines and lines[0].strip() == "【对话人格】":
        rest = "\n".join(lines[1:]).strip()
        return rest or body.strip()
    return body.strip()


def render_dialogue_block(pack: PersonaDistillPack, *, max_chars: int = _DIALOGUE_MAX_CHARS) -> str:
    """将 dialogue 切片渲染为 Speak 注入块（自然语言自述，约 200 字）。"""
    body = _normalize_dialogue_body(pack.dialogue_text())
    if not body:
        return ""
    return _trunc(body, max_chars)


def render_dialogue_from_snapshot(
    persona_distill: dict | PersonaDistillPack | None,
    *,
    max_chars: int = _DIALOGUE_MAX_CHARS,
) -> str:
    if persona_distill is None:
        return ""
    if isinstance(persona_distill, PersonaDistillPack):
        return render_dialogue_block(persona_distill, max_chars=max_chars)
    if isinstance(persona_distill, dict):
        pack = PersonaDistillPack.from_dict(persona_distill)
        return render_dialogue_block(pack, max_chars=max_chars)
    return ""
