from __future__ import annotations

import json
from typing import Any

from .bundle import SpeakPromptBundle

ModuleSection = tuple[str, str, str]


def build_module_sections(
    bundle: SpeakPromptBundle,
    *,
    system_assembled: str | None = None,
) -> list[ModuleSection]:
    sections: list[ModuleSection] = []

    if text := bundle.persona.identity.narrative.strip():
        sections.append(("persona.identity", "人格 · 自叙", text))
    if text := bundle.persona.identity.stable_source.strip():
        sections.append(("persona.identity.stable", "人格 · 稳定源", text))
    if text := bundle.persona.presence.state.strip():
        sections.append(("persona.presence.state", "人格 · 近期状态源", text))
    if text := bundle.persona.presence.instant_mood.strip():
        sections.append(("persona.presence.mood", "人格 · 瞬间情绪", text))
    if text := bundle.persona.relational.interactor_portrait.strip():
        sections.append(("persona.relational", "人格 · 对话者画像", text))

    if text := bundle.guidance.interactor_portrait.strip():
        sections.append(("guidance.interactor", "引导 · 规划器对话者摘要", text))
    if text := bundle.guidance.recall_preview.strip():
        sections.append(("guidance.recall", "引导 · 记忆候选", text))
    if text := bundle.guidance.share_preview.strip():
        sections.append(("guidance.share_preview", "引导 · 分享候选", text))

    if bundle.scene.world_scene.strip():
        sections.append(
            ("scene.world", "叙事 · 世界场景", bundle.scene.world_scene.strip()),
        )
    if bundle.scene.scene_name.strip():
        sections.append(
            ("scene.name", "叙事 · 场景名", bundle.scene.scene_name.strip()),
        )
    if bundle.scene.transition_text.strip():
        sections.append(
            ("scene.transition", "叙事 · 场景转化", bundle.scene.transition_text.strip()),
        )

    pull = bundle.meta.get("trace_pull")
    if isinstance(pull, dict):
        _append_pull_trace(sections, pull)

    if bundle.system.role.strip():
        sections.append(("system.role", "系统 · 角色", bundle.system.role.strip()))
    if bundle.guidance.control_arc.strip():
        sections.append(
            ("guidance.control_arc", "引导 · 对话引导", bundle.guidance.control_arc.strip()),
        )
    for idx, block in enumerate(bundle.guidance.social_blocks):
        text = block.strip()
        if text:
            sections.append((f"guidance.social.{idx}", "引导 · 社交", text))
    if bundle.guidance.context_distill.strip():
        sections.append(
            (
                "guidance.context_distill",
                "会话 · 上下文蒸馏",
                bundle.guidance.context_distill.strip(),
            )
        )
    if bundle.guidance.working_memory.strip():
        sections.append(
            (
                "guidance.working_memory",
                "会话 · 工作记忆（最近轮次）",
                bundle.guidance.working_memory.strip(),
            )
        )
    if bundle.share_summary.strip():
        sections.append(
            ("orchestrator.share_summary", "orchestrator · share_summary", bundle.share_summary.strip()),
        )
    if bundle.system.output_format.strip():
        sections.append(("system.output_format", "系统 · 输出格式", bundle.system.output_format.strip()))

    if bundle.notes:
        sections.append(("orchestrator.notes", "orchestrator · notes", "\n".join(bundle.notes)))

    assembled = system_assembled if system_assembled is not None else bundle.build_system()
    sections.append(
        (
            "llm.assembly",
            "LLM · system 拼接（送入模型）",
            _format_system_assembly_note(bundle, assembled),
        )
    )
    sections.append(("llm.user", "LLM · user（送入模型）", bundle.user_text or ""))

    coordinator = bundle.meta.get("turn_coordinator")
    if isinstance(coordinator, dict):
        refresh = coordinator.get("module_refresh")
        if refresh:
            sections.append(
                (
                    "session.module_refresh",
                    "会话 · 当轮模块刷新标记",
                    json.dumps(refresh, ensure_ascii=False),
                ),
            )
        ledger = coordinator.get("inject_ledger")
        if ledger:
            sections.append(
                (
                    "session.inject_ledger",
                    "会话 · 记忆注入账本",
                    json.dumps(ledger, ensure_ascii=False),
                ),
            )

    director = bundle.meta.get("session_director")
    if isinstance(director, dict):
        sections.append(
            ("session.director", "会话 · 导演决策", json.dumps(director, ensure_ascii=False, indent=2)),
        )

    typing = bundle.meta.get("session_typing")
    if isinstance(typing, dict):
        sections.append(
            ("session.typing", "会话 · 打字态", json.dumps(typing, ensure_ascii=False)),
        )

    brew = bundle.meta.get("session_brew_queue")
    if isinstance(brew, dict):
        sections.append(
            ("session.brew_queue", "会话 · 酝酿队列", json.dumps(brew, ensure_ascii=False)),
        )

    if bundle.meta:
        meta_copy = {
            k: v
            for k, v in bundle.meta.items()
            if k
            not in (
                "trace_pull",
                "turn_coordinator",
                "session_director",
                "session_typing",
                "session_brew_queue",
            )
        }
        if meta_copy:
            sections.append(
                ("orchestrator.meta", "orchestrator · meta", json.dumps(meta_copy, ensure_ascii=False, indent=2)),
            )

    return sections


def _format_system_assembly_note(bundle: SpeakPromptBundle, assembled: str) -> str:
    parts: list[str] = []
    if bundle.system.role.strip():
        parts.append(f"system.role({len(bundle.system.role.strip())})")
    if bundle.persona.self_narrative.strip():
        parts.append(f"persona.self_narrative({len(bundle.persona.self_narrative.strip())})")
    if bundle.persona.identity.narrative.strip():
        parts.append(
            f"persona.identity({len(bundle.persona.identity.narrative.strip())})"
        )
    if bundle.persona.presence.instant_mood.strip():
        parts.append(
            f"persona.presence.mood({len(bundle.persona.presence.instant_mood.strip())})"
        )
    if bundle.persona.relational.interactor_portrait.strip():
        parts.append(
            "persona.relational("
            f"{len(bundle.persona.relational.interactor_portrait.strip())})"
        )
    if bundle.scene.world_scene.strip():
        parts.append(f"scene.world({len(bundle.scene.world_scene.strip())})")
    if bundle.guidance.control_arc.strip():
        parts.append(f"guidance.control_arc({len(bundle.guidance.control_arc.strip())})")
    social_chars = sum(len(block.strip()) for block in bundle.guidance.social_blocks if block.strip())
    if social_chars:
        parts.append(f"guidance.social({social_chars})")
    if bundle.guidance.context_distill.strip():
        parts.append(
            f"guidance.context_distill({len(bundle.guidance.context_distill.strip())})"
        )
    if bundle.guidance.working_memory.strip():
        parts.append(
            f"guidance.working_memory({len(bundle.guidance.working_memory.strip())})"
        )
    if bundle.system.output_format.strip():
        parts.append(f"system.output_format({len(bundle.system.output_format.strip())})")
    order = " → ".join(parts) if parts else "(空)"
    stitch = (
        "system.role → orchestrator( persona + interactor + scene + guidance ) → "
        "context_distill → working_memory → system.output_format（prompt_stitch）"
    )
    return (
        f"拼接顺序: {order}\n"
        f"调度框: {stitch}\n"
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
        social_lines = mem.get("social_prefetch_lines") or []
        if social_lines:
            body = "\n".join(f"- {line}" for line in social_lines if str(line).strip())
            sections.append(("memory.pull.social_prefetch", "记忆 · Social 预取", body))
        warm_lines = mem.get("warm_spread_lines") or []
        if warm_lines:
            body = "\n".join(f"- {line}" for line in warm_lines if str(line).strip())
            sections.append(("memory.pull.warm_spread", "记忆 · 预热 spread", body))
        sections.append(
            (
                "memory.pull.meta",
                "记忆 · 拉取元数据",
                f"inject_turn={mem.get('inject_turn_index')} "
                f"inject_unit_ids={mem.get('inject_unit_ids')} "
                f"sources={mem.get('sources')} "
                f"keyword_wait_ms={mem.get('keyword_wait_ms')} "
                f"merge_ratio={mem.get('merge_ratio')} "
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
