from __future__ import annotations

from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object


class DynamicLayerDirector:
    """
    动态层指挥家：自由组装记忆/分享/传递信息进角色上下文，并把握对话动向。

    轮询阶段还可决定 terminate_round——终止导演本轮对上下文窗口的改写与重排，
    直到下一次轮询或用户入站。
    """

    name = "dynamic_layer"

    def __init__(self, llm: DirectorLLMCaller | None = None) -> None:
        self._llm = llm

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
        share_wants: bool = False,
        poll: bool = False,
    ) -> DirectorOutput:
        meta = snapshot.orchestrator.compose_meta or {}
        mem_ids = [str(x) for x in (meta.get("dynamic_memory_ids") or [])]
        mem_texts = [str(x) for x in (meta.get("dynamic_memory_texts") or [])]
        share_texts = [str(x) for x in (meta.get("dynamic_share_texts") or [])]
        dir_texts = [str(x) for x in (meta.get("compose_manager_director_memory_texts") or [])]
        text = user_text.strip() or snapshot.dialogue.user_text.strip()

        payload = {
            "inject_memory": False,
            "memory_unit_ids": [],
            "inject_share": False,
            "share_indices": [],
            "pass_info": False,
            "terminate_round": False,
            "reason": "default_none",
            "poll": poll,
        }
        reason = "heuristic"
        if self._llm is not None and self._llm.available:
            decided = self._decide_llm(
                snapshot,
                user_text=text,
                mem_ids=mem_ids,
                mem_texts=mem_texts,
                share_texts=share_texts,
                dir_texts=dir_texts,
                share_wants=share_wants,
                poll=poll,
            )
            if decided is not None:
                payload.update(decided)
                reason = str(decided.get("reason") or "director_llm")
                return DirectorOutput(director=self.name, payload=payload, reason=reason)

        # 无 LLM：保守启发式——轮询时放开分享/传递；入站默认不硬灌
        if poll:
            payload["inject_share"] = bool(share_wants and share_texts)
            payload["share_indices"] = [0] if payload["inject_share"] else []
            payload["pass_info"] = bool(dir_texts)
            payload["inject_memory"] = bool(mem_texts)
            payload["memory_unit_ids"] = list(mem_ids[:1]) if mem_ids else []
            # 无新材料可排时终止本轮改写，等待用户或下次轮询
            payload["terminate_round"] = not (
                payload["inject_share"] or payload["inject_memory"] or payload["pass_info"]
            )
            payload["reason"] = "poll_open_schedule"
            reason = "poll_open_schedule"
        else:
            payload["inject_memory"] = bool(mem_texts) and len(text) >= 8
            payload["memory_unit_ids"] = list(mem_ids[:1]) if payload["inject_memory"] else []
            payload["inject_share"] = bool(share_wants and share_texts)
            payload["share_indices"] = [0] if payload["inject_share"] else []
            payload["pass_info"] = False
            payload["terminate_round"] = False
            payload["reason"] = "ingress_conservative"
            reason = "ingress_conservative"
        return DirectorOutput(director=self.name, payload=payload, reason=reason)

    def _decide_llm(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        mem_ids: list[str],
        mem_texts: list[str],
        share_texts: list[str],
        dir_texts: list[str],
        share_wants: bool,
        poll: bool,
    ) -> dict | None:
        phase = "poll" if poll else "ingress"
        terminate_rule = (
            "轮询阶段你还必须决定 terminate_round："
            "true=本轮导演动作到此为止，不再改写/重排上下文窗口，等待用户输入或下一次轮询；"
            "false=仍可继续本轮后续导演动作。\n"
            if poll
            else "入站阶段 terminate_round 必须为 false。\n"
        )
        prompt = (
            "你是对话动态层指挥家。ComposeManager 只提供材料库存；"
            "由你自由组装记忆、待分享内容与传递信息进角色上下文，并把握对话动向。\n"
            f"阶段={phase}。\n"
            f"{terminate_rule}"
            "不得调度系统提示词或人格画像（它们不在动态层）。\n"
            f"user_text={user_text[:300]}\n"
            f"share_wants={share_wants}\n"
            f"memory_candidates={list(zip(mem_ids, mem_texts))[:6]}\n"
            f"share_candidates={share_texts[:4]}\n"
            f"director_info_candidates={dir_texts[:4]}\n"
            "只输出 JSON："
            '{"inject_memory":true|false,"memory_unit_ids":["id",...],'
            '"inject_share":true|false,"share_indices":[0],'
            '"pass_info":true|false,'
            '"terminate_round":true|false,"reason":"..."}'
        )
        raw = self._llm.generate_json(
            system=(
                "动态层指挥家：自由组装上下文并把握动向；"
                "材料层不得自行注入；轮询时可终止本轮改写以等待用户。"
            ),
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        data = extract_json_object(raw)
        if not data:
            return None
        mem_ids_out = data.get("memory_unit_ids") or []
        if not isinstance(mem_ids_out, list):
            mem_ids_out = []
        share_idx = data.get("share_indices") or []
        if not isinstance(share_idx, list):
            share_idx = []
        terminate = bool(data.get("terminate_round")) if poll else False
        return {
            "inject_memory": bool(data.get("inject_memory")),
            "memory_unit_ids": [str(x) for x in mem_ids_out if str(x).strip()],
            "inject_share": bool(data.get("inject_share")),
            "share_indices": [int(x) for x in share_idx if str(x).lstrip("-").isdigit()],
            "pass_info": bool(data.get("pass_info")),
            "terminate_round": terminate,
            "reason": str(data.get("reason") or "director_llm"),
            "poll": poll,
        }


def apply_dynamic_layer_terminate(state, output: DirectorOutput) -> bool:
    """若导演终止本轮动作，冻结上下文改写直到新轮询/用户入站。"""
    terminate = bool((output.payload or {}).get("terminate_round"))
    state.director_context_frozen = terminate
    return terminate
