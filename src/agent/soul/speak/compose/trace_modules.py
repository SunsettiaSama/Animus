from __future__ import annotations

from typing import Any

from .bundle import SpeakPromptBundle

ModuleSection = tuple[str, str, str]


def build_module_sections(
    bundle: SpeakPromptBundle,
    *,
    system_assembled: str | None = None,
) -> list[ModuleSection]:
    """(module_id, 标题, 该模块注入 speak 的原文)。"""
    sections: list[ModuleSection] = []
    inj = bundle.injected
    sys_p = bundle.system

    if inj.persona.traits.strip():
        sections.append(("persona.traits", "人格 · 特质", inj.persona.traits.strip()))
    if inj.persona.self_concept.strip():
        sections.append(("persona.self_concept", "人格 · 自我概念", inj.persona.self_concept.strip()))

    if inj.status.presence.strip():
        sections.append(("status.presence", "状态 · presence", inj.status.presence.strip()))
    if inj.status.dialogue_compressed.strip():
        sections.append(
            ("status.dialogue_compressed", "状态 · 会话蒸馏摘要", inj.status.dialogue_compressed.strip())
        )
    if inj.status.interactor_portrait.strip():
        sections.append(
            ("status.interactor_portrait", "状态 · 对话者画像", inj.status.interactor_portrait.strip())
        )
    if inj.status.similar_memories.strip():
        sections.append(
            ("status.similar_memories", "状态 · 相似记忆注入块", inj.status.similar_memories.strip())
        )

    pull = bundle.meta.get("trace_pull")
    if isinstance(pull, dict):
        _append_pull_trace(sections, pull)

    if sys_p.role.strip():
        sections.append(("system.role", "系统 · 角色", sys_p.role.strip()))
    if sys_p.share.strip():
        sections.append(("system.share", "系统 · 分享意图", sys_p.share.strip()))
    if bundle.share_summary.strip():
        sections.append(("compose.share_summary", "compose · share_summary", bundle.share_summary.strip()))
    if sys_p.output_format.strip():
        sections.append(("system.output_format", "系统 · 输出格式", sys_p.output_format.strip()))

    if bundle.notes:
        sections.append(("compose.notes", "compose · notes", "\n".join(bundle.notes)))

    assembled = system_assembled if system_assembled is not None else bundle.build_system()
    sections.append(
        (
            "llm.assembly",
            "LLM · system 拼接（送入模型）",
            _format_system_assembly_note(bundle, assembled),
        )
    )
    sections.append(("llm.user", "LLM · user（送入模型）", bundle.user_text or ""))

    if bundle.meta:
        import json

        meta_copy = {k: v for k, v in bundle.meta.items() if k != "trace_pull"}
        if meta_copy:
            sections.append(
                ("compose.meta", "compose · meta", json.dumps(meta_copy, ensure_ascii=False, indent=2)),
            )

    return sections


def _format_system_assembly_note(bundle: SpeakPromptBundle, assembled: str) -> str:
    """system 由各模块按 build_system 顺序拼接；正文已在上面分段列出。"""
    parts: list[str] = []
    if bundle.system.role.strip():
        parts.append(f"role({len(bundle.system.role.strip())})")
    if bundle.injected.persona.traits.strip():
        parts.append(f"persona.traits({len(bundle.injected.persona.traits.strip())})")
    if bundle.injected.persona.self_concept.strip():
        parts.append(f"persona.self_concept({len(bundle.injected.persona.self_concept.strip())})")
    if bundle.injected.status.presence.strip():
        parts.append(f"status.presence({len(bundle.injected.status.presence.strip())})")
    if bundle.injected.status.dialogue_compressed.strip():
        parts.append(
            f"status.dialogue_compressed({len(bundle.injected.status.dialogue_compressed.strip())})"
        )
    if bundle.injected.status.interactor_portrait.strip():
        parts.append(
            f"status.interactor_portrait({len(bundle.injected.status.interactor_portrait.strip())})"
        )
    if bundle.injected.status.similar_memories.strip():
        parts.append(
            f"status.similar_memories({len(bundle.injected.status.similar_memories.strip())})"
        )
    if bundle.system.share.strip():
        parts.append(f"system.share({len(bundle.system.share.strip())})")
    if bundle.system.output_format.strip():
        parts.append(f"system.output_format({len(bundle.system.output_format.strip())})")
    order = " → ".join(parts) if parts else "(空)"
    return (
        f"拼接顺序: {order}\n"
        f"总长 {len(assembled)} chars\n"
        "各段正文见上文对应模块，此处不重复全文。"
    )


def _append_pull_trace(sections: list[ModuleSection], pull: dict[str, Any]) -> None:
    mem = pull.get("memory")
    if isinstance(mem, dict):
        inject_lines = mem.get("inject_lines") or []
        if inject_lines:
            body = "\n".join(f"- {line}" for line in inject_lines if str(line).strip())
            sections.append(("memory.pull.inject", "记忆 · 拉取注入（原始行）", body))
        spill_lines = mem.get("spill_lines") or []
        if spill_lines:
            body = "\n".join(f"- {line}" for line in spill_lines if str(line).strip())
            sections.append(("memory.pull.spill", "记忆 · 拉取溢出（未注入）", body))
        sections.append(
            (
                "memory.pull.meta",
                "记忆 · 拉取元数据",
                f"inject_turn={mem.get('inject_turn_index')} "
                f"inject_unit_ids={mem.get('inject_unit_ids')} "
                f"spill_turn={mem.get('spill_turn_index')} "
                f"spill_unit_ids={mem.get('spill_unit_ids')}",
            ),
        )
    portrait = pull.get("portrait")
    if isinstance(portrait, dict) and portrait.get("portrait_text"):
        sections.append(
            (
                "memory.portrait",
                "记忆 · 对话者画像（拉取原文）",
                str(portrait.get("portrait_text", "")).strip(),
            ),
        )
