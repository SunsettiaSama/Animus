from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)


def note_plot_bound_delivery(
    state: Any,
    *,
    plot_unit_ids: tuple[str, ...] | list[str],
    reason: str = "character_delivery",
) -> str:
    """角色交付只记账，不推进 plot_arc。

    剧情 unit 完成权：导演确认 → 编剧 confirm_interaction_unit_complete。
    本函数把「本拍绑定了哪张剧情卡」写入导演可见证据，供下一拍判 complete。
    返回当前 active intent（空串表示未绑定到当前卡）。
    """
    wanted = {
        str(pid).strip()
        for pid in (plot_unit_ids or ())
        if str(pid).strip()
    }
    if not wanted:
        return ""
    plot_arc = getattr(state, "plot_arc", None)
    if plot_arc is None or not getattr(plot_arc, "ready", False):
        return ""
    active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
    if active is None:
        return ""
    active_id = str(getattr(active, "unit_id", "") or "").strip()
    if not active_id or active_id not in wanted:
        return ""
    cache = getattr(state, "director_cache", None)
    if isinstance(cache, dict):
        evidence = list(cache.get("plot_unit_delivery_evidence") or [])
        evidence.append(
            {
                "plot_unit_id": active_id,
                "intent": str(getattr(active, "intent", "") or "").strip()[:120],
                "reason": str(reason or "").strip()[:80],
                "poll_seq": int(getattr(state, "poll_seq", 0) or 0),
            }
        )
        cache["plot_unit_delivery_evidence"] = evidence[-12:]
    notes = getattr(state, "notes", None)
    if isinstance(notes, list):
        notes.append(
            f"plot_queue: delivery_noted unit={active_id} "
            f"(await_director_confirm) reason={str(reason or '')[:40]}"
        )
    return str(getattr(active, "intent", "") or "").strip()


def resolve_injected_memory_ids(
    schedule: DynamicLayerSchedule,
    materials: DynamicLayerMaterials,
) -> tuple[str, ...]:
    return schedule.selected_memory_ids(materials)


def resolve_injected_share(
    schedule: DynamicLayerSchedule,
    materials: DynamicLayerMaterials,
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    texts = schedule.selected_share_texts(materials)
    indices = schedule.selected_share_indices(materials)
    return texts, indices


def consume_injected_materials(
    session_id: str,
    *,
    memory_unit_ids: tuple[str, ...],
    share_texts: tuple[str, ...],
    share_indices: tuple[int, ...],
    mark_recall_unit_consumed: Callable[[str, str], None] | None,
    pop_session_share_at: Callable[[str, int], Any] | None,
    pop_presence_share_at: Callable[[str, int], bool] | None,
    peek_session_share: Callable[[str], list[dict[str, object]]] | None,
    pop_deferred_share_matching: Callable[[str, str], bool] | None = None,
    clear_director_inject_flags: Callable[[str], None] | None = None,
) -> list[str]:
    """角色本轮已看见的记忆/分享：完成消费，禁止下一轮再压入同一条。"""
    sid = session_id.strip()
    notes: list[str] = []
    for uid in memory_unit_ids:
        uid_s = str(uid or "").strip()
        if not uid_s or mark_recall_unit_consumed is None:
            continue
        mark_recall_unit_consumed(sid, uid_s)
        notes.append(f"character_memory_consumed:{uid_s}")

    remaining_texts = [str(t).strip() for t in share_texts if str(t).strip()]
    # 优先按 session 队列 topic 匹配弹出（index 可能因合并列表漂移）
    if peek_session_share is not None and pop_session_share_at is not None:
        for text in list(remaining_texts):
            items = peek_session_share(sid) or []
            matched = False
            for idx, item in enumerate(items):
                topic = str(item.get("topic") or "").strip()
                if topic and topic == text:
                    if pop_session_share_at(sid, idx) is not None:
                        notes.append(f"character_share_consumed_session:{text[:48]}")
                        remaining_texts.remove(text)
                        matched = True
                    break
            if matched:
                continue

    # 再按导演给出的 share_indices 尝试 presence 队列
    if pop_presence_share_at is not None:
        for index in sorted(set(int(i) for i in share_indices), reverse=True):
            if pop_presence_share_at(sid, index):
                notes.append(f"character_share_consumed_presence_idx:{index}")

    if pop_deferred_share_matching is not None:
        for text in list(remaining_texts):
            if pop_deferred_share_matching(sid, text):
                notes.append(f"character_share_consumed_deferred:{text[:48]}")
                remaining_texts.remove(text)

    if clear_director_inject_flags is not None and (
        memory_unit_ids or share_texts or share_indices
    ):
        clear_director_inject_flags(sid)
        notes.append("character_dynamic_inject_flags_cleared")
    return notes
