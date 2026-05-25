from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.soul.presence.interface_config import InterfaceReactConfig

from .actions import ReactAction
from .context import SessionContextRetriever
from .parser import ReactActionCall
from .speak_outbound import PresenceReactOutbound

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class ReactActionExecutor:
    """轻量 ReAct action 执行器。"""

    def __init__(
        self,
        soul: SoulService,
        *,
        cfg: InterfaceReactConfig | None = None,
        context_retriever: SessionContextRetriever | None = None,
        speak_outbound: PresenceReactOutbound | None = None,
    ) -> None:
        self._soul = soul
        self._cfg = cfg or InterfaceReactConfig.default()
        self._context = context_retriever or SessionContextRetriever(soul, cfg=self._cfg)
        self._outbound = speak_outbound or PresenceReactOutbound(soul)

    @property
    def context_retriever(self) -> SessionContextRetriever:
        return self._context

    @property
    def speak_outbound(self) -> PresenceReactOutbound:
        return self._outbound

    def execute(self, session_id: str, call: ReactActionCall) -> dict[str, Any]:
        if call.action not in self._cfg.allowed_action_set:
            raise ValueError(f"react action 未允许: {call.action!r}")

        if call.action == ReactAction.MEMORY_RECALL:
            return self._memory_recall(call.action_args)

        if call.action == ReactAction.JOURNAL_STATUS:
            return self._journal_status(call.action_args)

        if call.action == ReactAction.SESSION_CONTEXT:
            return self._session_context(session_id, call.action_args)

        if call.action == ReactAction.SPEAK_TO_USER:
            return self._speak_to_user(session_id, call.action_args)

        raise ValueError(f"unknown react action: {call.action!r}")

    def _memory_recall(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("memory_recall 需要 query")
        top_k = args.get("top_k")
        emotional_context = str(args.get("emotional_context", ""))
        if top_k is not None:
            result = self._soul.recall_memory(
                query,
                top_k=int(top_k),
                emotional_context=emotional_context,
            )
        else:
            result = self._soul.recall_memory(
                query,
                emotional_context=emotional_context,
            )
        return {"action": ReactAction.MEMORY_RECALL, "result": result}

    def _journal_status(self, args: dict[str, Any]) -> dict[str, Any]:
        n = int(args.get("recent_n", 3))
        journal = self._soul.life.api.journal
        digest = journal.to_digest()
        limit = self._cfg.journal_digest_max_chars
        if len(digest) > limit:
            digest = digest[:limit]
        return {
            "action": ReactAction.JOURNAL_STATUS,
            "empty": journal.is_empty(),
            "digest": digest,
            "today_remaining_slots": journal.today_remaining_slots(),
            "due_landmarks": len(journal.due_landmarks()),
            "recent_done": journal.recent_done_intent_lines(n),
        }

    def _session_context(
        self,
        session_id: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        top_k_raw = args.get("top_k")
        top_k = int(top_k_raw) if top_k_raw is not None else None
        sid = str(args.get("session_id", session_id))
        result = self._context.retrieve(sid, query=query, top_k=top_k)
        return {"action": ReactAction.SESSION_CONTEXT, **result.to_dict()}

    def _speak_to_user(self, session_id: str, args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message", "")).strip()
        if not message:
            raise ValueError("speak_to_user 需要 message")
        wait_reply = bool(args.get("wait_reply", True))
        append = bool(args.get("append", False))
        result = self._outbound.deliver_agent_message(
            session_id=str(args.get("session_id", session_id)),
            message=message,
            wait_reply=wait_reply,
            append=append,
            source="react:speak_to_user",
        )
        return {"action": ReactAction.SPEAK_TO_USER, **result}
