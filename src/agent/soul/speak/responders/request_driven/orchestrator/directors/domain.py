from __future__ import annotations

from typing import TYPE_CHECKING

from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object

if TYPE_CHECKING:
    pass


class MemoryInjectDirector:
    """记忆导演：可对共享 staging 做有限干预（默认每轮最多 1 条，由 ComposeManager 强制）。"""

    name = "memory_inject"

    def __init__(self, llm: DirectorLLMCaller | None = None) -> None:
        self._llm = llm

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput:
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        request_emergence = len(text) >= 12
        request_keyword = "?" in text or "吗" in text
        meta = snapshot.orchestrator.compose_meta or {}
        intervene_max = int(meta.get("intervene_max", 1) or 1)
        dir_ids = list(meta.get("compose_manager_director_memory_ids") or [])
        dir_texts = list(meta.get("compose_manager_director_memory_texts") or [])
        role_ids = list(meta.get("compose_manager_role_memory_ids") or [])
        role_texts = list(meta.get("compose_manager_role_memory_texts") or [])

        action = "none"
        unit_id = ""
        inject_text = ""
        reason = "memory_heuristic"
        if self._llm is not None and self._llm.available and (dir_texts or role_texts or text):
            decided = self._decide_intervention(
                snapshot,
                user_text=text,
                dir_ids=dir_ids,
                dir_texts=dir_texts,
                role_ids=role_ids,
                role_texts=role_texts,
                intervene_max=intervene_max,
            )
            if decided is not None:
                action, unit_id, inject_text, reason = decided

        return DirectorOutput(
            director=self.name,
            payload={
                "request_emergence": request_emergence,
                "request_keyword": request_keyword,
                "request_portrait": snapshot.signals.turn_index % 3 == 0,
                "include_recall": True,
                "include_portrait": True,
                "buffer_action": action,
                "unit_id": unit_id,
                "text": inject_text,
                "intervene_max": intervene_max,
                "role_memory_ids": role_ids,
                "director_memory_ids": dir_ids,
            },
            reason=reason,
        )

    def _decide_intervention(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        dir_ids: list,
        dir_texts: list,
        role_ids: list,
        role_texts: list,
        intervene_max: int,
    ) -> tuple[str, str, str, str] | None:
        if intervene_max < 1:
            return ("none", "", "", "intervene_disabled")
        prompt = (
            "你是记忆干预导演。共享临时记忆库；你有独立检索结果，也可看见角色检索结果。\n"
            f"每轮最多干预 {intervene_max} 条：inject 一条新记忆，或 remove 一条已有 unit_id，或 none。\n"
            "不要过度干预；默认 none。\n"
            f"user_text={user_text[:300]}\n"
            f"director_hits={list(zip(dir_ids, dir_texts))[:5]}\n"
            f"role_hits_visible={list(zip(role_ids, role_texts))[:5]}\n"
            '只输出 JSON：{"action":"none|inject|remove","unit_id":"","text":"","reason":""}'
        )
        raw = self._llm.generate_json(
            system="记忆干预导演，严格遵守干预条数上限。",
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            return None
        action = str(payload.get("action") or "none").strip().lower()
        if action not in ("none", "inject", "remove"):
            action = "none"
        return (
            action,
            str(payload.get("unit_id") or "").strip(),
            str(payload.get("text") or "").strip(),
            str(payload.get("reason") or "director_llm").strip() or "director_llm",
        )


class ShareImpulseDirector:
    name = "share_impulse"

    def run(self, snapshot: SessionSnapshot, *, share_wants: bool = False) -> DirectorOutput:
        return DirectorOutput(
            director=self.name,
            payload={
                "include_preview": share_wants,
                "include_in_planner": share_wants,
                "share_queue_count": int(
                    snapshot.orchestrator.compose_meta.get("share_queue_count", 0),
                ),
            },
            reason="share_state",
        )


class SocialArmDirector:
    name = "social_arm"

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        silence_armed: bool = False,
        social_armed: str | None = None,
    ) -> DirectorOutput:
        return DirectorOutput(
            director=self.name,
            payload={
                "social_armed": social_armed,
                "silence_armed": silence_armed,
                "turn_index": snapshot.signals.turn_index,
            },
            reason="social_snapshot",
        )


class InterruptDirector:
    name = "interrupt"

    def run(self, snapshot: SessionSnapshot) -> DirectorOutput:
        reorder = False
        cancel_unsent = False
        if snapshot.runtime.push_phase == "pushing":
            reorder = snapshot.runtime.current_segment_index < snapshot.runtime.segment_total
            cancel_unsent = reorder
        return DirectorOutput(
            director=self.name,
            payload={
                "reorder": reorder,
                "cancel_unsent": cancel_unsent,
                "force_reply": False,
            },
            reason="interrupt_async",
        )
